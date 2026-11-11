"""Stage 5 - LOAD: write the analysis-ready tables to CSV and SQLite."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any

import pandas as pd

CSV_TABLES = {
    "syllabi_clean": "syllabi_clean.csv",
    "topic_classifications": "topic_classifications.csv",
    "syllabus_coverage_topics": "syllabus_coverage_topics.csv",
    "syllabus_coverage_outcomes": "syllabus_coverage_outcomes.csv",
}

SQLITE_TABLES = {
    "syllabi_clean": "syllabi",
    "topic_classifications": "topic_classifications",
    "syllabus_coverage_topics": "coverage_topics",
    "syllabus_coverage_outcomes": "coverage_outcomes",
}


def export(
    tables: dict[str, pd.DataFrame],
    quality: dict[str, Any],
    processed_dir: str | Path,
) -> dict[str, str]:
    """Persist all tables + the quality report; returns the written paths."""
    out = Path(processed_dir)
    out.mkdir(parents=True, exist_ok=True)
    written: dict[str, str] = {}

    for key, filename in CSV_TABLES.items():
        df = tables.get(key)
        if df is None:
            continue
        path = out / filename
        df.to_csv(path, index=False, encoding="utf-8")
        written[key] = str(path)

    quality_path = out / "quality_report.json"
    quality_path.write_text(
        json.dumps(quality, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    written["quality_report"] = str(quality_path)

    db_path = out / "syllabi.db"
    with sqlite3.connect(db_path) as conn:
        for key, table in SQLITE_TABLES.items():
            df = tables.get(key)
            if df is None:
                continue
            df.to_sql(table, conn, if_exists="replace", index=False)
        conn.execute("VACUUM")
    written["sqlite"] = str(db_path)

    return written
