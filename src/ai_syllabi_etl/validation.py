"""v1 PDF-flow validation: normalize-then-assert at the validation boundary.

The pipeline normalizes the dataset (``year`` values -> ISO dates where
parseable; empty->null and alias->canonical vocabulary mapping already
happened at the extraction seam) and then asserts that the *exact records
about to be written* satisfy the schema contract — so a PASS certifies the
file on disk. Severity model:

- **Fail the run (exit 1)**: the file-count gate (N distinct-hash files in
  -> N records out), structural contract violations, and unmappable
  vocabulary values (not resolvable via the alias map and not
  ``Other/not clear``).
- **Warn only**: completeness metrics, scan and per-file failure records,
  and sentinel-like values appearing in PDF output (the extractor emits
  real nulls, so sentinels are a backstop).

Every normalization the validator applies is recorded in the record's
extraction-log entry under ``normalizations``, so each change is auditable.

(This is the v1 PDF-flow validator; ``validate.py`` is the legacy CSV-flow
validator and is retired by the CSV-archival ticket.)
"""

from __future__ import annotations

import datetime as _dt
import re
from typing import Any

from .schema import FIELD_COLUMNS, SchemaContract, validate_record

STATUS_ORDER = {"pass": 0, "warn": 1, "fail": 2}

# Sentinel-like strings that mean "nothing stated" if a backend ever emits
# them. The PDF extractor emits real nulls, so these should never appear;
# the check exists as a backstop (warn-only), mirroring the legacy set.
SENTINEL_LIKE = frozenset(
    {
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
)

# year -> ISO date patterns. The form's "Year?" format is "Month, day,
# year"; the owner's manual export stored bare years as YYYY-01-01, so a
# bare year normalizes to YYYY-01-01 too. Unparseable values stay verbatim.
_YEAR = re.compile(r"^(\d{4})$")
_YEAR_MONTH = re.compile(r"^(\d{4})-(\d{1,2})$")
_ISO_DATE = re.compile(r"^(\d{4})-(\d{2})-(\d{2})$")
_US_DATE = re.compile(r"^(\d{1,2})/(\d{1,2})/(\d{4})$")
_MONTH_NAME = {
    m: i
    for i, m in enumerate(
        [
            "january",
            "february",
            "march",
            "april",
            "may",
            "june",
            "july",
            "august",
            "september",
            "october",
            "november",
            "december",
        ],
        start=1,
    )
}
for _short, _full in (
    ("jan", "january"),
    ("feb", "february"),
    ("mar", "march"),
    ("apr", "april"),
    ("jun", "june"),
    ("jul", "july"),
    ("aug", "august"),
    ("sep", "september"),
    ("sept", "september"),
    ("oct", "october"),
    ("nov", "november"),
    ("dec", "december"),
):
    _MONTH_NAME[_short] = _MONTH_NAME[_full]
_MONTH_YEAR = re.compile(r"^([A-Za-z]+)\.?\s+(\d{4})$")
_MONTH_DAY_YEAR = re.compile(r"^([A-Za-z]+)\.?\s+(\d{1,2}),?\s+(\d{4})$")


def _iso_or_none(year: int, month: int, day: int) -> str | None:
    """``YYYY-MM-DD`` when the triple is a real date, else ``None``."""
    try:
        return _dt.date(year, month, day).isoformat()
    except ValueError:
        return None


def normalize_year(value: Any) -> tuple[Any, tuple[str, str] | None]:
    """Normalize one ``year`` value to an ISO date where parseable.

    Returns ``(value, action)``: ``action`` is ``None`` when nothing
    changed, else ``(from, to)`` for the log. Supported inputs (case-
    insensitive month names): ``YYYY`` -> ``YYYY-01-01``; ``YYYY-MM`` ->
    ``YYYY-MM-01``; ``YYYY-MM-DD`` (already ISO, validated); ``M/D/YYYY``
    (the US form convention); ``Month YYYY`` and ``Month D, YYYY``.
    Anything else (seasons like ``Fall 2024``, academic-year ranges) stays
    verbatim — normalization never invents data.
    """
    if not isinstance(value, str):
        return value, None
    text = " ".join(value.split())
    if m := _YEAR.match(text):
        iso = _iso_or_none(int(m.group(1)), 1, 1)
    elif m := _YEAR_MONTH.match(text):
        iso = _iso_or_none(int(m.group(1)), int(m.group(2)), 1)
    elif m := _ISO_DATE.match(text):
        iso = _iso_or_none(int(m.group(1)), int(m.group(2)), int(m.group(3)))
    elif m := _US_DATE.match(text):
        iso = _iso_or_none(int(m.group(3)), int(m.group(1)), int(m.group(2)))
    elif m := _MONTH_DAY_YEAR.match(text):
        month = _MONTH_NAME.get(m.group(1).lower())
        iso = (
            _iso_or_none(int(m.group(3)), month, int(m.group(2)))
            if month
            else None
        )
    elif m := _MONTH_YEAR.match(text):
        month = _MONTH_NAME.get(m.group(1).lower())
        iso = _iso_or_none(int(m.group(2)), month, 1) if month else None
    else:
        iso = None
    if iso is None or text == iso:
        return value, None
    return iso, (value, iso)


def validate_dataset(
    records: list[dict[str, Any]], log: dict[str, Any], contract: SchemaContract
) -> tuple[dict[str, Any], list[dict[str, Any]], dict[str, Any]]:
    """Normalize then assert the dataset; return ``(report, records, log)``.

    Normalization mutates the given records in place (they are the ones
    written to disk) and appends a ``normalizations`` list to every log
    entry. The report has the ``{"overall", "checks", "completeness_pct"}``
    shape; ``overall`` is the worst check status (pass < warn < fail).
    """
    checks: list[dict[str, str]] = []

    def add(name: str, status: str, detail: str) -> None:
        checks.append({"name": name, "status": status, "detail": detail})

    entries = {}
    for e in log.get("records", []):
        e.setdefault("normalizations", [])
        entries[e.get("syllabus_id")] = e

    # ---- normalize: ISO dates where parseable (auditable) -----------------
    for record in records:
        actions: list[dict[str, str]] = []
        new_year, action = normalize_year(record.get("year"))
        if action is not None:
            record["year"] = new_year
            actions.append(
                {"field": "year", "from": action[0], "to": action[1], "rule": "iso_date"}
            )
        entry = entries.get(record.get("syllabus_id"))
        if entry is not None:
            entry["normalizations"] = actions
            # (an unmatched entry keeps its initialized empty list)

    # ---- fail: file-count gate (N distinct-hash files -> N records) -------
    distinct = int(log.get("distinct_files", 0))
    if len(records) == distinct:
        add(
            "file_count_gate",
            "pass",
            f"{distinct} distinct-hash files -> {len(records)} records",
        )
    else:
        add(
            "file_count_gate",
            "fail",
            f"{distinct} distinct-hash files but {len(records)} records "
            "(no file may be silently lost)",
        )

    # ---- fail: assert the exact records-to-be-written ---------------------
    structural: list[str] = []
    unmappable: list[str] = []
    for record in records:
        for issue in validate_record(record, contract):
            name = issue.get("value", "")
            detail = (
                f"{record.get('source_file', '<unknown>')}: "
                f"{issue['field']}: {issue['issue']}"
            )
            if name:
                detail += f" {name!r}"
            if issue["issue"] == "unmapped_value":
                unmappable.append(detail)
            else:
                structural.append(detail)
    if structural:
        add(
            "record_contract",
            "fail",
            "records violate the schema contract: " + "; ".join(structural),
        )
    else:
        add("record_contract", "pass", f"all {len(records)} records match the contract")
    if unmappable:
        add(
            "unmappable_vocabulary_values",
            "fail",
            "values not mappable to a canonical vocabulary choice (add an "
            "alias in schema_contract.yaml or emit Other/not clear): "
            + "; ".join(unmappable),
        )
    else:
        add(
            "unmappable_vocabulary_values",
            "pass",
            "every vocabulary value is canonical (or Other/not clear)",
        )

    # ---- warn: completeness per form field --------------------------------
    n = len(records)
    if n == 0:
        completeness = {col: 0.0 for col in FIELD_COLUMNS}
        add("completeness", "pass", "no records to measure")
    else:
        completeness = {
            col: round(100.0 * sum(1 for r in records if r.get(col) is not None) / n, 1)
            for col in FIELD_COLUMNS
        }
        empty = [col for col, pct in completeness.items() if pct == 0.0]
        if empty:
            add(
                "completeness",
                "warn",
                f"{len(empty)} form field(s) entirely empty across all records: "
                + ", ".join(empty),
            )
        else:
            add("completeness", "pass", "every form field has at least one value")

    # ---- warn: scan / failed extraction records ---------------------------
    bad = [e for e in log.get("records", []) if e.get("status") != "ok"]
    if bad:
        counts: dict[str, int] = {}
        for e in bad:
            counts[e["status"]] = counts.get(e["status"], 0) + 1
        names = ", ".join(e["source_file"] for e in bad)
        add(
            "scan_or_failed_records",
            "warn",
            f"{len(bad)} record(s) with status {counts} (all-null): {names}",
        )
    else:
        add("scan_or_failed_records", "pass", "every file extracted a record")

    # ---- warn: sentinel-like values in PDF output (backstop) --------------
    residues: dict[str, int] = {}
    for col in FIELD_COLUMNS:
        count = 0
        for record in records:
            value = record.get(col)
            values = value if isinstance(value, (list, tuple)) else [value]
            count += sum(
                1
                for v in values
                if isinstance(v, str) and " ".join(v.split()).lower() in SENTINEL_LIKE
            )
        if count:
            residues[col] = count
    if residues:
        add(
            "sentinel_values",
            "warn",
            "sentinel-like strings in PDF output (extractor should emit "
            f"real nulls): {residues}",
        )
    else:
        add("sentinel_values", "pass", "no sentinel-like values in PDF output")

    overall = "pass"
    for check in checks:
        if STATUS_ORDER[check["status"]] > STATUS_ORDER[overall]:
            overall = check["status"]

    return {
        "overall": overall,
        "checks": checks,
        "completeness_pct": completeness,
    }, records, log
