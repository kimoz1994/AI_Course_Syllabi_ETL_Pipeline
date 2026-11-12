"""Command line interface.

v1 is the PDF-only flow: a folder of syllabus PDFs in, one clean dataset
file + an extraction log out (extract -> validate -> write). ``run``
executes it; the legacy CSV/XLSX table flow (its stages and its stage
subcommands) was retired when the PDF flow went end-to-end — the Kaggle
CSV lives archived in ``data/archive``. Classification remains in the
codebase but dormant, off the v1 run path (deferred ticket).
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Any

from . import __version__
from .config import ConfigError, load_config
from .pdf_intake import IntakeError


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="ai-syllabi-etl",
        description=(
            "PDF-only ETL pipeline for AI course syllabi: a folder of syllabus "
            "PDFs -> dedup -> text -> extract (14-field schema) -> validate "
            "-> syllabi_dataset.csv + extraction_log.json."
        ),
    )
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    sub = parser.add_subparsers(dest="command", required=True)

    sp = sub.add_parser("run", help="run the PDF-only pipeline")
    sp.add_argument("--config", default=None, help="path to config.yaml")
    sp.add_argument("--input", default=None, help="override the input PDF folder")
    sp.add_argument(
        "--force",
        action="store_true",
        help="re-extract every PDF, bypassing the extraction cache",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        cfg = load_config(args.config)
        if args.input:
            input_path = Path(args.input)
            if not input_path.is_absolute():
                input_path = (Path.cwd() / input_path).resolve()
            cfg["input"] = str(input_path)
        if args.force:
            cfg["force"] = True
        if not Path(cfg["input"]).is_dir():
            raise ConfigError(
                f"input must be a folder of syllabus PDFs, got {cfg['input']!r}: "
                "table ingestion (CSV/XLSX) was retired — the Kaggle CSV lives "
                "archived in data/archive/ and is no longer an input"
            )
        from .pdf_intake import run_pdf_pipeline

        return run_pdf_pipeline(cfg)
    except (ConfigError, IntakeError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    except Exception as exc:  # pragma: no cover - top-level safety net
        print(f"unexpected error: {exc}", file=sys.stderr)
        raise


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
