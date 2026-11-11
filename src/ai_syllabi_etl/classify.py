"""Stage 3 - CLASSIFY: label syllabus topics/outcomes with the AIMA taxonomy.

Three interchangeable backends:

* ``rule``   - deterministic keyword matching against ``taxonomy/*.json``
  (offline; used by the tests, CI, and as a graceful LLM fallback).
* ``openai`` - any OpenAI-compatible chat-completions server: LM Studio,
  Ollama, vLLM, or a cloud API, configured through ``config.yaml``.
* ``mock``   - canned responses for unit tests.
"""

from __future__ import annotations

import json
import os
import re
import time
from dataclasses import dataclass, field as dataclass_field
from pathlib import Path
from typing import Any, Protocol

import pandas as pd
import requests

from .clean import split_outcomes, split_topic_items

OTHER_ID = 7

FIELD_SPLITTERS = {
    "course_topics": split_topic_items,
    "course_outcomes": split_outcomes,
}

CLASSIFIED_COLUMNS = [
    "syllabus_id",
    "field",
    "item_index",
    "topic_text",
    "class_id",
    "label",
    "backend",
    "confidence",
]


class ClassificationError(RuntimeError):
    """Raised when a backend cannot classify a batch."""


# ---------------------------------------------------------------------------
# Taxonomy
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class TaxonomyClass:
    id: int
    name: str
    keywords: tuple[str, ...] = ()


@dataclass(frozen=True)
class Taxonomy:
    classes: tuple[TaxonomyClass, ...]
    source: str = ""

    @classmethod
    def load(cls, path: str | Path) -> "Taxonomy":
        p = Path(path)
        if not p.is_file():
            raise ClassificationError(f"taxonomy file not found: {p}")
        data = json.loads(p.read_text(encoding="utf-8"))
        classes = tuple(
            TaxonomyClass(
                id=int(c["id"]),
                name=str(c["name"]),
                keywords=tuple(str(k).lower() for k in c.get("keywords", [])),
            )
            for c in data["classes"]
        )
        ids = [c.id for c in classes]
        if len(ids) != len(set(ids)) or OTHER_ID not in ids:
            raise ClassificationError("taxonomy ids must be unique and include id 7 (Other)")
        return cls(classes=classes, source=str(data.get("source", "")))

    @property
    def by_id(self) -> dict[int, TaxonomyClass]:
        return {c.id: c for c in self.classes}

    @property
    def ids(self) -> set[int]:
        return {c.id for c in self.classes}

    @property
    def name_of(self) -> dict[int, str]:
        return {c.id: c.name for c in self.classes}

    def prompt_block(self) -> str:
        lines = []
        for c in sorted(self.classes, key=lambda x: x.id):
            if c.keywords:
                lines.append(f"{c.id}. {c.name}\n   Content/keywords: {', '.join(c.keywords)}")
            else:
                lines.append(f"{c.id}. {c.name} (use only when none of classes 1-6 fit)")
        return "\n".join(lines)


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------


def normalize_topic(text: str) -> str:
    return re.sub(r"\s+", " ", str(text)).strip().lower()


def _has_keyword(low_text: str, keyword: str) -> bool:
    """Word-boundary keyword match that tolerates plurals.

    Uses lookarounds so ``search`` does not match inside ``research``;
    symbolic keywords (e.g. ``a*``) fall back to a plain substring test.
    """
    pattern = rf"(?<![a-z0-9]){re.escape(keyword)}s?(?![a-z0-9])"
    if re.search(pattern, low_text):
        return True
    if not re.fullmatch(r"[a-z0-9 ]*", keyword):
        return keyword in low_text
    return False


def _extract_json(content: str) -> dict[str, Any]:
    """Pull the first usable JSON object out of an LLM response."""
    candidates: list[str] = []
    fence = re.search(r"```(?:json)?\s*(.*?)```", content, re.S)
    if fence:
        candidates.append(fence.group(1))
    start, end = content.find("{"), content.rfind("}")
    if start != -1 and end > start:
        candidates.append(content[start : end + 1])
    for candidate in candidates:
        try:
            obj = json.loads(candidate)
        except json.JSONDecodeError:
            continue
        if isinstance(obj, dict):
            return obj
    raise ClassificationError("no JSON object found in LLM response")


def _coerce_class(value: Any, taxonomy: Taxonomy) -> int | None:
    """Accept ``5``, ``"5"``, ``"5. Machine Learning"`` or a class name."""
    cid: int | None = None
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)) and float(value).is_integer():
        cid = int(value)
    elif isinstance(value, str):
        match = re.search(r"\d+", value)
        if match:
            cid = int(match.group(0))
        else:
            wanted = value.strip().lower()
            for c in taxonomy.classes:
                if c.name.lower() == wanted:
                    return c.id
    if cid is not None and cid in taxonomy.ids:
        return cid
    return None


@dataclass
class ClassifiedItem:
    syllabus_id: str
    field: str
    item_index: int
    topic_text: str
    class_id: int
    label: str
    backend: str
    confidence: float | None = None


# ---------------------------------------------------------------------------
# Backends
# ---------------------------------------------------------------------------


class Backend(Protocol):
    name: str

    def classify_batch(
        self, syllabus_id: str, field: str, texts: list[str]
    ) -> list[tuple[int, float]]:
        """Return ``(class_id, confidence)`` aligned with *texts*."""
        ...


class RuleBackend:
    """Deterministic keyword scoring against the taxonomy."""

    name = "rule"

    def __init__(self, taxonomy: Taxonomy):
        self.taxonomy = taxonomy

    def score_text(self, text: str) -> tuple[int, float]:
        low = text.lower()
        best_id, best_hits, best_len = OTHER_ID, 0, 0
        for cls in self.taxonomy.classes:
            if cls.id == OTHER_ID:
                continue
            hits = [k for k in cls.keywords if _has_keyword(low, k)]
            if not hits:
                continue
            total_len = sum(len(k) for k in hits)
            if len(hits) > best_hits or (len(hits) == best_hits and total_len > best_len):
                best_id, best_hits, best_len = cls.id, len(hits), total_len
        confidence = min(1.0, best_hits / 3.0)
        return best_id, confidence

    def classify_batch(
        self, syllabus_id: str, field: str, texts: list[str]
    ) -> list[tuple[int, float]]:
        return [self.score_text(t) for t in texts]


class MockBackend:
    """Canned substring -> class responses (unit tests only)."""

    name = "mock"

    def __init__(
        self,
        taxonomy: Taxonomy,
        responses: dict[str, int] | None = None,
        default: int = OTHER_ID,
    ):
        self.taxonomy = taxonomy
        self.responses = {k.lower(): v for k, v in (responses or {}).items()}
        self.default = default

    def classify_batch(
        self, syllabus_id: str, field: str, texts: list[str]
    ) -> list[tuple[int, float]]:
        results: list[tuple[int, float]] = []
        for text in texts:
            low = text.lower()
            cid = self.default
            for needle, value in self.responses.items():
                if needle in low:
                    cid = value
                    break
            results.append((cid, 1.0))
        return results


class OpenAICompatibleBackend:
    """Chat-completions client for LM Studio / Ollama / vLLM / cloud APIs."""

    name = "openai"

    def __init__(
        self,
        llm_cfg: dict[str, Any],
        taxonomy: Taxonomy,
        prompt_path: str | Path,
        rule_fallback: RuleBackend | None = None,
    ):
        self.base_url = str(llm_cfg.get("base_url", "http://localhost:1234/v1")).rstrip("/")
        self.model = str(llm_cfg.get("model", ""))
        self.temperature = float(llm_cfg.get("temperature", 0.0))
        self.timeout = float(llm_cfg.get("timeout_seconds", 60))
        self.max_retries = max(1, int(llm_cfg.get("max_retries", 3)))
        self.fallback_to_rule = bool(llm_cfg.get("fallback_to_rule", True))
        self.api_key = os.environ.get(str(llm_cfg.get("api_key_env", "")), "") or "local"
        self.taxonomy = taxonomy
        self.rule = rule_fallback

        prompt_file = Path(prompt_path)
        if not prompt_file.is_file():
            raise ClassificationError(f"prompt file not found: {prompt_file}")
        raw = prompt_file.read_text(encoding="utf-8")
        # the file documents itself before the first horizontal rule
        self.template = raw.split("\n---\n", 1)[-1].strip()
        if "<<<TAXONOMY>>>" not in self.template or "<<<TEXT>>>" not in self.template:
            raise ClassificationError("prompt template must contain <<<TAXONOMY>>> and <<<TEXT>>>")

    # -- transport ---------------------------------------------------------
    def _chat(self, user_content: str) -> str:
        url = f"{self.base_url}/chat/completions"
        payload = {
            "model": self.model,
            "temperature": self.temperature,
            "messages": [
                {
                    "role": "system",
                    "content": "You classify AI course syllabus topics into a fixed taxonomy. "
                    "Return only the requested JSON.",
                },
                {"role": "user", "content": user_content},
            ],
        }
        headers = {"Authorization": f"Bearer {self.api_key}"}
        response = requests.post(
            url, json=payload, headers=headers, timeout=self.timeout
        )
        response.raise_for_status()
        data = response.json()
        return data["choices"][0]["message"]["content"]

    # -- parsing -----------------------------------------------------------
    def _parse_response(self, content: str) -> dict[str, int]:
        obj = _extract_json(content)
        topics = obj.get("topics")
        if not isinstance(topics, list):
            raise ClassificationError("LLM response is missing the 'topics' list")
        mapping: dict[str, int] = {}
        for entry in topics:
            if not isinstance(entry, dict):
                continue
            text = str(entry.get("topic", "")).strip()
            cid = _coerce_class(entry.get("class"), self.taxonomy)
            if text and cid is not None:
                mapping[normalize_topic(text)] = cid
        if not mapping:
            raise ClassificationError("LLM response contained no usable topic entries")
        return mapping

    # -- public ------------------------------------------------------------
    def classify_batch(
        self, syllabus_id: str, field: str, texts: list[str]
    ) -> list[tuple[int, float]]:
        if not texts:
            return []
        user = self.template.replace("<<<TAXONOMY>>>", self.taxonomy.prompt_block())
        user = user.replace("<<<TEXT>>>", "\n".join(f"- {t}" for t in texts))

        last_error: Exception | None = None
        for attempt in range(1, self.max_retries + 1):
            try:
                content = self._chat(user)
                mapping = self._parse_response(content)
                results: list[tuple[int, float]] = []
                for text in texts:
                    cid = mapping.get(normalize_topic(text))
                    if cid is None:
                        # model skipped or reworded this item - degrade locally
                        cid, conf = (
                            self.rule.score_text(text)
                            if self.rule is not None
                            else (OTHER_ID, 0.0)
                        )
                        results.append((cid, conf))
                    else:
                        results.append((cid, 1.0))
                return results
            except Exception as exc:  # network, HTTP, or parse failure
                last_error = exc
                if attempt < self.max_retries:
                    time.sleep(2 ** (attempt - 1))

        if self.fallback_to_rule and self.rule is not None:
            return self.rule.classify_batch(syllabus_id, field, texts)
        raise ClassificationError(
            f"LLM classification failed after {self.max_retries} attempts: {last_error}"
        )


def make_backend(cfg: dict[str, Any], taxonomy: Taxonomy) -> Any:
    """Instantiate the backend named in the configuration."""
    kind = str(cfg.get("backend", "rule")).lower()
    rule = RuleBackend(taxonomy)
    if kind == "rule":
        return rule
    if kind == "mock":
        return MockBackend(taxonomy)
    if kind == "openai":
        return OpenAICompatibleBackend(
            cfg.get("llm", {}), taxonomy, cfg.get("prompt", ""), rule_fallback=rule
        )
    raise ClassificationError(f"unknown backend {kind!r}; use rule, openai or mock")


# ---------------------------------------------------------------------------
# Pipeline-level helpers
# ---------------------------------------------------------------------------


def classify_dataframe(
    clean_df: pd.DataFrame,
    taxonomy: Taxonomy,
    backend: Any,
    fields: tuple[str, ...] = ("course_topics", "course_outcomes"),
) -> pd.DataFrame:
    """Classify every topic/outcome item in *clean_df* (long format)."""
    rows: list[dict[str, Any]] = []
    for record in clean_df.to_dict(orient="records"):
        sid = record.get("syllabus_id")
        for field_name in fields:
            splitter = FIELD_SPLITTERS.get(field_name)
            if splitter is None or field_name not in record:
                continue
            items = splitter(record.get(field_name))
            if not items:
                continue
            results = backend.classify_batch(sid, field_name, items)
            if len(results) != len(items):  # pragma: no cover - defensive
                raise ClassificationError(
                    f"backend returned {len(results)} results for {len(items)} items"
                )
            for idx, (text, (cid, conf)) in enumerate(zip(items, results), start=1):
                rows.append(
                    {
                        "syllabus_id": sid,
                        "field": field_name,
                        "item_index": idx,
                        "topic_text": text,
                        "class_id": cid,
                        "label": taxonomy.name_of.get(cid, f"Unknown ({cid})"),
                        "backend": backend.name,
                        "confidence": conf,
                    }
                )
    return pd.DataFrame(rows, columns=CLASSIFIED_COLUMNS)


def coverage_table(
    class_df: pd.DataFrame,
    taxonomy: Taxonomy,
    total_syllabi: int,
    field: str | None = None,
) -> pd.DataFrame:
    """Per-class item counts and syllabus coverage (``pct_syllabi``)."""
    df = class_df if field is None else class_df[class_df["field"] == field]
    rows = []
    for cls in sorted(taxonomy.classes, key=lambda c: c.id):
        sub = df[df["class_id"] == cls.id]
        n_syllabi = int(sub["syllabus_id"].nunique())
        rows.append(
            {
                "class_id": cls.id,
                "class_name": cls.name,
                "n_topics": int(len(sub)),
                "n_syllabi": n_syllabi,
                "pct_syllabi": round(100.0 * n_syllabi / total_syllabi, 1)
                if total_syllabi
                else 0.0,
            }
        )
    return pd.DataFrame(rows)
