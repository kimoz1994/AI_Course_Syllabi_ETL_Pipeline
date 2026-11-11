"""Stage 2 - CLEAN: standardize the Google-Form export.

Turns the raw questionnaire-style headers (``"Which country ? "``) into
stable snake_case columns, converts sentinel strings (``"not mentioned"``)
to missing values, parses the year, and normalizes whitespace - while
recording every applied rule so cleaning is auditable.
"""

from __future__ import annotations

import re
import unicodedata
from typing import Any

import pandas as pd

# ---------------------------------------------------------------------------
# Column mapping
# ---------------------------------------------------------------------------

#: normalized raw header -> clean column name
EXPECTED_COLUMNS: dict[str, str] = {
    "which country": "country",
    "which education institution": "institution",
    "year": "year",
    "what is the course title": "course_title",
    "what are the course prerequisites": "prerequisites",
    "what is the course description": "course_description",
    "what is the course content/topics": "course_topics",
    "what are the course outcomes/objectives": "course_outcomes",
    "hardware or software tools used in the course": "tools",
    "textbook/references used in the course": "textbooks",
    "teaching method": "teaching_methods",
    "what are assessment methods": "assessment_methods",
}

SENTINELS = {
    "",
    "not mentioned",
    "n/a",
    "na",
    "none",
    "-",
    "--",
    "not specified",
    "not available",
    "none mentioned",
    "not applicable",
    "no prerequisites",
}

_ID_COLUMN = "syllabus_id"
_YEAR_RE = re.compile(r"(\d{4})")
_BULLET_RE = re.compile(r"^\s*(?:[○•▪◦‣●·*+-]|\d+[.)])\s*")
_NUMBERED_RE = re.compile(r"^\s*\d+[.)]\s*")


class CleanError(RuntimeError):
    """Raised when the raw table cannot be standardized."""


def normalize_header(column: Any) -> str:
    """Collapse whitespace, lowercase, drop a trailing question mark."""
    text = unicodedata.normalize("NFKC", str(column))
    text = re.sub(r"\s+", " ", text).strip().lower()
    text = text.rstrip("?").strip()
    return text


def snake_case(text: str) -> str:
    """Fallback header conversion for columns not in :data:`EXPECTED_COLUMNS`."""
    text = normalize_header(text)
    text = re.sub(r"[^a-z0-9]+", "_", text)
    return text.strip("_") or "column"


def standardize_columns(df: pd.DataFrame) -> tuple[pd.DataFrame, list[dict[str, str]]]:
    """Rename raw questionnaire headers to clean snake_case names."""
    rename: dict[str, str] = {}
    log: list[dict[str, str]] = []
    used: set[str] = set()

    for col in df.columns:
        key = normalize_header(col)
        if key in EXPECTED_COLUMNS:
            target = EXPECTED_COLUMNS[key]
        else:
            target = snake_case(str(col))
            log.append({"rule": "fallback_header", "column": str(col), "result": target})
        if target in used:  # pragma: no cover - defensive against dup headers
            target = f"{target}_2"
        used.add(target)
        rename[col] = target

    return df.rename(columns=rename), log


def is_sentinel(value: Any) -> bool:
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return True
    if pd.isna(value):
        return True
    return str(value).strip().lower() in SENTINELS


def clean_text(value: Any, preserve_newlines: bool = True) -> str | None:
    """Normalize one cell: NFKC, tidy whitespace, sentinels -> ``None``."""
    if is_sentinel(value):
        return None
    text = unicodedata.normalize("NFKC", str(value))
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = re.sub(r"[ \t]+", " ", text)
    if preserve_newlines:
        text = re.sub(r"\n{3,}", "\n\n", text)
    else:
        text = re.sub(r"\s+", " ", text)
    text = "\n".join(line.strip() for line in text.split("\n"))
    text = text.strip()
    return text or None


def parse_year(value: Any) -> int | None:
    """Extract a plausible 4-digit year from forms like ``2018-01-01``."""
    if is_sentinel(value):
        return None
    match = _YEAR_RE.search(str(value))
    if not match:
        return None
    year = int(match.group(1))
    return year if 1900 <= year <= 2100 else None


def split_items(value: Any, seps: tuple[str, ...] = (";", "|")) -> list[str]:
    """Split a multi-value cell on separators, dropping empty fragments."""
    text = clean_text(value, preserve_newlines=True)
    if not text:
        return []
    pattern = "|".join(re.escape(s) for s in seps)
    parts = re.split(pattern, text)
    items = [p.strip() for p in parts]
    return [p for p in items if p]


def split_outcomes(value: Any) -> list[str]:
    """Split numbered/bulleted outcome lines, stripping the numbering."""
    text = clean_text(value, preserve_newlines=True)
    if not text:
        return []
    items = []
    for line in text.split("\n"):
        line = _NUMBERED_RE.sub("", line).strip()
        line = _BULLET_RE.sub("", line).strip()
        if line:
            items.append(line)
    return items


def split_topic_items(value: Any) -> list[str]:
    """Split a topics blob on newlines and bullet markers.

    Commas are deliberately *not* used as separators: topic phrases such as
    ``"Search, A* and planning"`` would be chopped mid-phrase.
    """
    text = clean_text(value, preserve_newlines=True)
    if not text:
        return []
    items = []
    for line in text.split("\n"):
        line = _BULLET_RE.sub("", line).strip()
        if line:
            items.append(line)
    return items


def clean_dataframe(raw: pd.DataFrame) -> tuple[pd.DataFrame, list[dict[str, str]]]:
    """Standardize the raw table; returns ``(clean_df, cleaning_log)``.

    Every row is preserved (no filtering) and receives a stable
    ``syllabus_id`` so the raw and cleaned tables stay traceable 1:1.
    """
    if raw.empty:
        raise CleanError("raw table has no rows")

    df, log = standardize_columns(raw)
    df = df.copy()
    df.insert(0, _ID_COLUMN, [f"S{i:03d}" for i in range(1, len(df) + 1)])
    log.append({"rule": "assign_id", "column": "-", "result": _ID_COLUMN})

    text_columns = [
        c
        for c in df.columns
        if c != _ID_COLUMN and c != "year" and pd.api.types.is_object_dtype(df[c])
    ]
    for col in text_columns:
        before_missing = int(df[col].isna().sum())
        df[col] = df[col].map(lambda v: clean_text(v))
        after_missing = int(df[col].isna().sum())
        filled = after_missing - before_missing
        if filled > 0:
            log.append(
                {"rule": "sentinel_to_missing", "column": col, "result": str(filled)}
            )

    if "year" in df.columns:
        parsed = df["year"].map(parse_year)
        unparsed = int(df["year"].notna().sum() - parsed.notna().sum())
        df["year"] = parsed.astype("Int64")
        if unparsed:
            log.append({"rule": "year_unparsed", "column": "year", "result": str(unparsed)})

    return df, log
