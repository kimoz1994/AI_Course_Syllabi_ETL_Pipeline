"""Stage 4 - VALIDATE: data-quality gates, completeness and anomaly report.

Structural problems (lost rows, id collisions, unknown labels, missing
required columns) fail the run; coverage shortfalls and anomalies are
reported as warnings so imperfect-but-real data still flows through.
"""

from __future__ import annotations

from typing import Any

import pandas as pd

from .clean import SENTINELS
from .classify import Taxonomy

STATUS_ORDER = {"pass": 0, "warn": 1, "fail": 2}


def validate(
    raw_count: int,
    clean_df: pd.DataFrame,
    class_df: pd.DataFrame,
    taxonomy: Taxonomy,
    val_cfg: dict[str, Any],
) -> dict[str, Any]:
    """Run all quality gates; returns a JSON-serializable report."""
    checks: list[dict[str, str]] = []
    anomalies: list[dict[str, Any]] = []

    def add(name: str, status: str, detail: str) -> None:
        checks.append({"name": name, "status": status, "detail": detail})

    n = len(clean_df)

    # 1. row count preserved (cleaning must never drop records silently)
    if n == raw_count:
        add("row_count_preserved", "pass", f"{n} rows in, {n} rows out")
    else:
        add(
            "row_count_preserved",
            "fail",
            f"raw={raw_count} cleaned={n} (cleaning must not drop rows)",
        )

    # 2. stable unique ids
    ids = clean_df.get("syllabus_id")
    if ids is not None and ids.is_unique and ids.notna().all():
        add("unique_ids", "pass", f"{ids.nunique()} unique syllabus_id values")
    else:
        add("unique_ids", "fail", "syllabus_id values are missing or duplicated")

    # 3. required columns present after cleaning
    required = list(val_cfg.get("required_columns", []))
    missing = [c for c in required if c not in clean_df.columns]
    if not missing:
        add("required_columns", "pass", f"all {len(required)} required columns present")
    else:
        add("required_columns", "fail", f"missing columns: {', '.join(missing)}")

    # 4. no sentinel strings survive cleaning
    residues: dict[str, int] = {}
    for col in clean_df.columns:
        if col == "syllabus_id" or not pd.api.types.is_object_dtype(clean_df[col]):
            continue
        values = clean_df[col].dropna().astype(str).str.strip().str.lower()
        count = int(values.isin(SENTINELS).sum())
        if count:
            residues[col] = count
    if not residues:
        add("no_sentinel_residues", "pass", "no 'not mentioned' style values remain")
    else:
        add("no_sentinel_residues", "warn", f"sentinel values still present: {residues}")

    # 5. year plausibility
    min_year = int(val_cfg.get("min_year", 1900))
    max_year = int(val_cfg.get("max_year", 2100))
    if "year" in clean_df.columns:
        years = pd.to_numeric(clean_df["year"], errors="coerce")
        out_of_range = clean_df[(years.notna()) & ((years < min_year) | (years > max_year))]
        missing_year = int(years.isna().sum())
        detail = f"{int(years.notna().sum())} parsed, {missing_year} missing"
        if len(out_of_range):
            for _, row in out_of_range.iterrows():
                anomalies.append(
                    {
                        "type": "year_outlier",
                        "syllabus_id": row.get("syllabus_id"),
                        "detail": f"year {row.get('year')} outside {min_year}-{max_year}",
                    }
                )
            add("year_range", "warn", f"{len(out_of_range)} outlier year(s); {detail}")
        else:
            add("year_range", "pass", detail)

    # 6. topic coverage
    if "course_topics" in clean_df.columns and n:
        coverage = float(clean_df["course_topics"].notna().mean())
        threshold = float(val_cfg.get("min_topic_coverage", 0.8))
        detail = f"{coverage:.1%} of syllabi have topics (threshold {threshold:.0%})"
        add(
            "topic_coverage",
            "pass" if coverage >= threshold else "warn",
            detail,
        )

    # 7. classification labels are valid taxonomy ids
    if class_df is not None and len(class_df):
        unknown = sorted(set(class_df["class_id"]) - taxonomy.ids)
        if not unknown:
            add(
                "taxonomy_labels",
                "pass",
                f"{len(class_df)} items labelled with {class_df['class_id'].nunique()} classes",
            )
        else:
            add("taxonomy_labels", "fail", f"unknown class ids: {unknown}")
    else:
        add("taxonomy_labels", "warn", "no classified items")

    # 8. duplicate course records (same institution + title + year)
    dup_cols = [c for c in ("institution", "course_title", "year") if c in clean_df.columns]
    if len(dup_cols) == 3 and n:
        keyed = clean_df.dropna(subset=dup_cols)
        dupes = keyed[keyed.duplicated(subset=dup_cols, keep=False)]
        if len(dupes):
            for _, row in dupes.iterrows():
                anomalies.append(
                    {
                        "type": "duplicate_record",
                        "syllabus_id": row.get("syllabus_id"),
                        "detail": f"{row.get('institution')} / {row.get('course_title')} / {row.get('year')}",
                    }
                )
            add(
                "duplicate_records",
                "warn",
                f"{len(dupes)} rows share institution+title+year",
            )
        else:
            add("duplicate_records", "pass", "no duplicate institution+title+year records")

    # 9. completeness per column
    completeness = {
        col: round(100.0 * float(clean_df[col].notna().mean()), 1)
        for col in clean_df.columns
        if col != "syllabus_id"
    }

    overall = "pass"
    for check in checks:
        if STATUS_ORDER[check["status"]] > STATUS_ORDER[overall]:
            overall = check["status"]

    return {
        "overall": overall,
        "checks": checks,
        "completeness_pct": completeness,
        "anomalies": anomalies,
        "row_counts": {"raw": raw_count, "cleaned": n, "classified_items": int(len(class_df))},
    }
