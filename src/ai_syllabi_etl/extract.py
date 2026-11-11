"""Stage 1 - EXTRACT: read the raw syllabus table (CSV or XLSX).

The shipped dataset was produced manually from PDF syllabi through a Google
Form (one column per field), so the primary input is that structured export.
A minimal :class:`PdfExtractor` is provided as groundwork for direct PDF
intake (optional dependency: ``pypdf``).
"""

from __future__ import annotations

import re
from pathlib import Path

import pandas as pd

SUPPORTED_SUFFIXES = (".csv", ".xlsx", ".xls")


class ExtractError(RuntimeError):
    """Raised when the input file cannot be read."""


def load_table(path: str | Path) -> pd.DataFrame:
    """Load a CSV/XLSX table with every value kept as a string.

    All-string loading keeps raw forms like ``2018-01-01`` intact so the
    cleaning stage can parse them explicitly instead of relying on pandas'
    type inference.
    """
    p = Path(path)
    if not p.is_file():
        raise ExtractError(f"input file not found: {p}")

    suffix = p.suffix.lower()
    try:
        if suffix == ".csv":
            df = pd.read_csv(p, dtype=str)
        elif suffix in (".xlsx", ".xls"):
            df = pd.read_excel(p, dtype=str)
        elif suffix == ".pdf":
            raise ExtractError(
                "PDF input is on the roadmap: PDF -> structured columns needs an "
                "AI extraction step. Convert the syllabi to CSV/XLSX first "
                "(the shipped dataset was produced via a Google Form)."
            )
        else:
            raise ExtractError(
                f"unsupported input type {suffix!r}; expected one of {SUPPORTED_SUFFIXES} or .pdf"
            )
    except ExtractError:
        raise
    except Exception as exc:  # pragma: no cover - passthrough of parser errors
        raise ExtractError(f"failed to read {p}: {exc}") from exc

    if df.empty:
        raise ExtractError(f"input table is empty: {p}")
    return df


class PdfExtractor:
    """Minimal PDF text extraction (requires the optional ``pypdf`` extra)."""

    def __init__(self, path: str | Path):
        try:
            import pypdf  # type: ignore
        except ImportError as exc:
            raise ExtractError(
                "PDF support requires pypdf: pip install 'ai-syllabi-etl[pdf]'"
            ) from exc
        self.path = Path(path)
        self._reader = pypdf.PdfReader(str(self.path))

    def extract_text(self) -> str:
        return "\n".join((page.extract_text() or "") for page in self._reader.pages)

    def extract_section(self, *headings: str) -> str | None:
        """Capture the text under the first line matching any *headings*.

        Headings are matched case-insensitively as whole lines (e.g.
        ``"course outcomes"``, ``"objectives"``); capture stops at the next
        short heading-like line.
        """
        text = self.extract_text()
        lines = text.splitlines()
        want = [h.lower() for h in headings]
        start = None
        for i, line in enumerate(lines):
            low = line.strip().lower()
            if low and any(w in low for w in want) and len(low) < 80:
                start = i + 1
                break
        if start is None:
            return None
        captured: list[str] = []
        for line in lines[start:]:
            stripped = line.strip()
            if stripped and len(stripped) < 60 and captured and not stripped[-1:] in ".;:":
                # heading-like line: stop
                break
            captured.append(line)
        return "\n".join(captured).strip() or None


def extract(input_path: str | Path) -> pd.DataFrame:
    """Dispatch extraction by file type."""
    return load_table(input_path)


def looks_like_heading(line: str) -> bool:  # helper kept public for tests
    stripped = line.strip()
    return bool(stripped) and len(stripped) < 60 and re.search(r"[A-Za-z]", stripped) is not None
