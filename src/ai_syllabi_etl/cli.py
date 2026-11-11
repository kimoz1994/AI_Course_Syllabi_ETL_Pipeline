"""Command line interface.

Individual stage commands (``extract``, ``clean``, ``classify``, ``validate``,
``load``, ``report``) run the pipeline *up to* that stage; ``run`` executes
the full pipeline.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Any

from . import __version__
from .classify import Taxonomy, classify_dataframe, make_backend
from .clean import clean_dataframe
from .config import ConfigError, load_config
from .extract import ExtractError, extract
from .load import export
from .report import build_outputs
from .validate import validate

STAGES = ("extract", "clean", "classify", "validate", "load", "report")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="ai-syllabi-etl",
        description=(
            "ETL pipeline for AI course syllabi: extract -> clean -> classify "
            "(AIMA taxonomy) -> validate -> load -> report."
        ),
    )
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    sub = parser.add_subparsers(dest="command", required=True)

    helps = {
        "extract": "read the raw table and report its shape",
        "clean": "standardize columns, sentinels and years",
        "classify": "label topics/outcomes with the AIMA taxonomy",
        "validate": "run data-quality gates and print the report",
        "load": "write CSV + SQLite outputs",
        "report": "render figures, tables and report.md",
        "run": "run the full pipeline (default)",
    }
    for name in (*STAGES, "run"):
        sp = sub.add_parser(name, help=helps[name])
        sp.add_argument("--config", default=None, help="path to config.yaml")
        sp.add_argument("--input", default=None, help="override input file (csv/xlsx)")
        sp.add_argument(
            "--backend",
            choices=["rule", "openai", "mock"],
            default=None,
            help="override classification backend",
        )
    return parser


def _print_quality(quality: dict[str, Any]) -> None:
    print(f"\n  quality: {quality['overall'].upper()}")
    for check in quality["checks"]:
        mark = {"pass": "ok  ", "warn": "warn", "fail": "FAIL"}[check["status"]]
        print(f"    [{mark}] {check['name']}: {check['detail']}")
    if quality["anomalies"]:
        print(f"  anomalies: {len(quality['anomalies'])}")
        for anomaly in quality["anomalies"][:10]:
            print(f"    - {anomaly['type']}: {anomaly['syllabus_id']} {anomaly['detail']}")


def run_pipeline(cfg: dict[str, Any], up_to: str) -> int:
    """Execute stages in order up to *up_to* (inclusive)."""
    if up_to not in STAGES:
        raise ConfigError(f"unknown stage {up_to!r}")
    stop = STAGES.index(up_to)

    taxonomy = Taxonomy.load(cfg["taxonomy"])
    backend_name = str(cfg.get("backend", "rule"))

    # ---- extract ---------------------------------------------------------
    raw = extract(cfg["input"])
    print(f"[extract] {Path(cfg['input']).name}: {raw.shape[0]} rows x {raw.shape[1]} columns")
    if stop == 0:
        return 0

    # ---- clean -----------------------------------------------------------
    clean_df, log = clean_dataframe(raw)
    sentinels = sum(1 for entry in log if entry["rule"] == "sentinel_to_missing")
    print(
        f"[clean]    {clean_df.shape[1]} columns, {clean_df.shape[0]} rows preserved, "
        f"{sentinels} column(s) had sentinel values converted"
    )
    if stop == 1:
        return 0

    # ---- classify --------------------------------------------------------
    backend = make_backend(cfg, taxonomy)
    class_df = classify_dataframe(clean_df, taxonomy, backend)
    print(
        f"[classify] backend={backend.name}: {len(class_df)} items labelled "
        f"({class_df['syllabus_id'].nunique()} syllabi)"
    )
    if stop == 2:
        return 0

    # ---- validate --------------------------------------------------------
    quality = validate(len(raw), clean_df, class_df, taxonomy, cfg["validation"])
    _print_quality(quality)
    if stop == 3:
        return 1 if quality["overall"] == "fail" else 0

    # ---- load ------------------------------------------------------------
    from .classify import coverage_table

    total = len(clean_df)
    tables = {
        "syllabi_clean": clean_df,
        "topic_classifications": class_df,
        "syllabus_coverage_topics": coverage_table(class_df, taxonomy, total, field="course_topics"),
        "syllabus_coverage_outcomes": coverage_table(
            class_df, taxonomy, total, field="course_outcomes"
        ),
    }
    written = export(tables, quality, cfg["paths"]["processed"])
    print(f"[load]     {len(written)} files written to {cfg['paths']['processed']}")
    for key, path in written.items():
        print(f"           - {key}: {Path(path).name}")
    if stop == 4:
        return 1 if quality["overall"] == "fail" else 0

    # ---- report ----------------------------------------------------------
    outputs = build_outputs(
        clean_df, class_df, quality, taxonomy, cfg, backend_name=backend.name
    )
    print(f"[report]   {len(outputs)} files written to {cfg['paths']['output']}")
    for key, path in outputs.items():
        print(f"           - {key}: {Path(path).name}")

    if quality["overall"] == "fail":
        print("\nPipeline finished with FAILING quality gates.", file=sys.stderr)
        return 1
    print("\nPipeline finished successfully.")
    return 0


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        cfg = load_config(args.config)
        if args.input:
            input_path = Path(args.input)
            if not input_path.is_absolute():
                input_path = (Path.cwd() / input_path).resolve()
            cfg["input"] = str(input_path)
        if args.backend:
            cfg["backend"] = args.backend
        up_to = "report" if args.command == "run" else args.command
        return run_pipeline(cfg, up_to=up_to)
    except (ConfigError, ExtractError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    except Exception as exc:  # pragma: no cover - top-level safety net
        print(f"unexpected error: {exc}", file=sys.stderr)
        raise


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
