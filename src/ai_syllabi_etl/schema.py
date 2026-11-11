"""The 14-field schema contract for v1 PDF extraction.

The form spec (`reference/form questions .txt`) — not the legacy CSV —
defines the schema: 14 fields whose canonical names fix the dataset column
layout, plus the three **closed vocabularies** (`course_level`,
`teaching_method`, `assessment_methods`) whose canonical value strings and
synonym→canonical alias map live in ``schema_contract.yaml`` (config, not
code). The alias map is applied by :func:`normalize_record`; values it
cannot map to a canonical choice (and that are not ``Other/not clear``) are
*unmappable* and are surfaced for the validation stage to fail on.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

# The 14 form-field columns in dataset order. The legacy CSV exported only
# 12 of these (it merged/renamed two) — the form spec is canonical.
FIELD_COLUMNS = (
    "country",
    "institution",
    "year",
    "course_level",
    "target_audience",
    "course_title",
    "prerequisites",
    "course_description",
    "course_topics",
    "course_outcomes",
    "tools",
    "textbooks",
    "teaching_method",
    "assessment_methods",
)

# Fields whose value is a list of items (written to the dataset as a JSON
# array). Everything else is a single scalar (or null).
LIST_FIELDS = frozenset(
    {
        "course_topics",
        "course_outcomes",
        "tools",
        "textbooks",
        "teaching_method",
        "assessment_methods",
    }
)

# Fields restricted to a closed vocabulary. Single-choice fields are the
# vocabulary fields that are not in LIST_FIELDS (only `course_level`).
VOCAB_FIELDS = frozenset({"course_level", "teaching_method", "assessment_methods"})

# The sentinel the manual Google-Form export used for "nothing stated"; the
# PDF extractor emits real nulls, but a backend may still emit the word.
NOT_MENTIONED = "not mentioned"

# A legal distinct label in every closed vocabulary: the value is not one of
# the enumerated choices and that is a fact worth keeping, not an error.
OTHER_NOT_CLEAR = "Other/not clear"

DEFAULT_CONTRACT_PATH = Path(__file__).resolve().parents[2] / "schema_contract.yaml"


class SchemaContractError(RuntimeError):
    """Raised when the schema contract file is missing or malformed."""


@dataclass(frozen=True)
class SchemaContract:
    """Canonical vocabularies + alias map, loaded from ``schema_contract.yaml``."""

    vocabularies: dict[str, list[str]]
    aliases: dict[str, dict[str, str]]


def load_schema_contract(path: str | Path = DEFAULT_CONTRACT_PATH) -> SchemaContract:
    """Load and validate the contract file; raises :class:`SchemaContractError`."""
    p = Path(path)
    if not p.is_file():
        raise SchemaContractError(f"schema contract file not found: {p}")
    try:
        data = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
    except yaml.YAMLError as exc:
        raise SchemaContractError(f"invalid YAML in {p}: {exc}") from exc

    vocabularies = data.get("vocabularies") or {}
    aliases = data.get("aliases") or {}
    if not isinstance(vocabularies, dict) or not isinstance(aliases, dict):
        raise SchemaContractError(f"{p}: 'vocabularies' and 'aliases' must be mappings")
    for field in VOCAB_FIELDS:
        values = vocabularies.get(field)
        if not isinstance(values, list) or not values:
            raise SchemaContractError(f"{p}: missing vocabulary for {field!r}")
    contract = SchemaContract(
        vocabularies={f: [str(v) for v in vocabularies[f]] for f in vocabularies},
        aliases={f: {str(k).lower(): str(v) for k, v in m.items()} for f, m in aliases.items()},
    )
    unknown = set(contract.vocabularies) - VOCAB_FIELDS
    if unknown:
        raise SchemaContractError(f"{p}: vocabularies for unknown fields: {sorted(unknown)}")
    for field, mapping in contract.aliases.items():
        bad = set(mapping.values()) - set(contract.vocabularies.get(field, []))
        if bad:
            raise SchemaContractError(
                f"{p}: aliases for {field!r} point at non-canonical values: {sorted(bad)}"
            )
    return contract


def _norm_key(value: str) -> str:
    """Case- and whitespace-insensitive lookup key."""
    return " ".join(value.split()).lower()


def _map_vocab_value(
    field: str, raw: str, contract: SchemaContract
) -> tuple[str | None, str | None]:
    """Normalize one vocabulary value; return ``(value, unmapped_raw)``.

    Resolution order: alias map (case-insensitive) -> case-insensitive
    canonical match (snaps e.g. ``PHD`` to the exact canonical string).
    ``not mentioned`` normalizes to ``None``. Anything else is unmapped:
    the raw value is returned unchanged so validation can fail on it.
    """
    text = " ".join(str(raw).split())
    if text == "" or _norm_key(text) == NOT_MENTIONED:
        return None, None
    alias = contract.aliases.get(field, {}).get(_norm_key(text))
    if alias is not None:
        return alias, None
    for canonical in contract.vocabularies.get(field, ()):
        if _norm_key(canonical) == _norm_key(text):
            return canonical, None
    return text, text


def normalize_record(
    record: dict[str, Any], contract: SchemaContract
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """Apply the schema contract to a backend record (the normalization entry point).

    Returns ``(record, unmapped)``. Normalizations: empty strings -> real
    nulls; ``not mentioned`` -> null; vocabulary values -> canonical strings
    via the alias map (list items normalize one by one; ``not mentioned``
    items are dropped; duplicates collapse; an emptied list becomes null).
    Unmappable values stay in the record verbatim and are also returned in
    ``unmapped`` so the validation stage can fail on them.
    """
    out: dict[str, Any] = {}
    unmapped: list[dict[str, Any]] = []
    for field in FIELD_COLUMNS:
        if field not in record:
            continue
        value = record[field]
        if value is None:
            out[field] = None
            continue
        if field in VOCAB_FIELDS and field not in LIST_FIELDS:
            mapped, bad = _map_vocab_value(field, value, contract)
            if bad is not None:
                unmapped.append({"field": field, "value": bad})
            out[field] = mapped
            continue
        if field in LIST_FIELDS:
            if not isinstance(value, (list, tuple)):
                # Pass wrong types through untouched: validate_record rejects
                # them (wrong_type); mangling e.g. a string into a list of
                # characters would let garbage reach the dataset.
                out[field] = value
                continue
            items: list[str] = []
            for item in value:
                if not isinstance(item, str):
                    items.append(item)
                    continue
                if field in VOCAB_FIELDS:
                    mapped, bad = _map_vocab_value(field, item, contract)
                else:
                    mapped, bad = (item.strip() or None), None
                if bad is not None:
                    unmapped.append({"field": field, "value": bad})
                if mapped is not None and mapped not in items:
                    items.append(mapped)
            out[field] = items or None
            continue
        if isinstance(value, str):
            out[field] = value.strip() or None
        else:
            out[field] = value
    return out, unmapped


def validate_record(
    record: dict[str, Any], contract: SchemaContract
) -> list[dict[str, Any]]:
    """Validate a record against the contract; return a list of issues.

    An empty list means the record satisfies the 14-field contract.
    Issue kinds: ``missing_field`` (one of the 14 absent), ``wrong_type``
    (a list field that is not an array / a scalar field that is not a
    string or null), ``bad_item_type`` (non-string item in a list field),
    and ``unmapped_value`` (vocabulary value neither canonical, aliased,
    nor ``Other/not clear`` — the validation stage fails the run on those).
    Provenance keys beyond the 14 fields are ignored here.
    """
    issues: list[dict[str, Any]] = []
    for field in FIELD_COLUMNS:
        if field not in record:
            issues.append({"field": field, "issue": "missing_field"})
            continue
        value = record[field]
        if value is None:
            continue
        if field in LIST_FIELDS:
            if not isinstance(value, (list, tuple)):
                issues.append(
                    {"field": field, "issue": "wrong_type", "value": value}
                )
                continue
            for item in value:
                if not isinstance(item, str):
                    issues.append(
                        {"field": field, "issue": "bad_item_type", "value": item}
                    )
                    continue
                if field in VOCAB_FIELDS and item not in contract.vocabularies.get(field, []):
                    issues.append(
                        {"field": field, "issue": "unmapped_value", "value": item}
                    )
            continue
        if field in VOCAB_FIELDS:
            if not isinstance(value, str):
                issues.append({"field": field, "issue": "wrong_type", "value": value})
            elif value not in contract.vocabularies.get(field, []):
                issues.append(
                    {"field": field, "issue": "unmapped_value", "value": value}
                )
            continue
        if not isinstance(value, str):
            issues.append({"field": field, "issue": "wrong_type", "value": value})
    return issues
