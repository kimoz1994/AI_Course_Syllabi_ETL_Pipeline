"""T5: the CLI contract after the legacy CSV path is retired.

The CLI is the PDF-only flow's front door: ``run`` over a folder of PDFs
(the full run itself is covered by ``tests/test_pdf_pipeline.py``). These
tests pin the retirement seam: a table file is no longer an input — the
Kaggle CSV is archived — and the legacy stage subcommands are gone from
the parser. Classification stays in the codebase but dormant, off the
run path.
"""

import contextlib
import io
import tempfile
import unittest
from pathlib import Path

from ai_syllabi_etl.cli import build_parser, main

REPO = Path(__file__).resolve().parents[1]
ARCHIVED_CSV = REPO / "data" / "archive" / "AI_course_syllabi_CSV.csv"


def _run_capture_stderr(argv):
    stderr = io.StringIO()
    with contextlib.redirect_stderr(stderr):
        code = main(argv)
    return code, stderr.getvalue()


class RetirementSeamTests(unittest.TestCase):
    def test_archived_csv_exists_and_is_no_longer_the_raw_input(self):
        self.assertTrue(
            ARCHIVED_CSV.is_file(),
            "the Kaggle CSV must live in data/archive, kept for cross-checking",
        )
        self.assertFalse(
            (REPO / "data" / "raw" / "AI_course_syllabi_CSV.csv").is_file(),
            "the CSV must not stay at the raw-input location",
        )

    def test_file_input_is_refused_with_retirement_message(self):
        with tempfile.TemporaryDirectory(prefix="ai_syllabi_etl_t5_") as td:
            tmp = Path(td)
            csv_path = tmp / "table.csv"
            csv_path.write_text("country,institution\nNarnia,Stub U\n", encoding="utf-8")
            cfg_path = tmp / "config.yaml"
            cfg_path.write_text(
                "input: '"
                + str(csv_path).replace("\\", "/")
                + "'\npaths:\n  output: '"
                + str(tmp / "output").replace("\\", "/")
                + "'\n",
                encoding="utf-8",
            )
            code, err = _run_capture_stderr(["run", "--config", str(cfg_path)])
            self.assertEqual(code, 2)
            self.assertIn("PDF", err)
            self.assertIn("archive", err)

    def test_stage_subcommands_are_gone(self):
        for stage in ("extract", "clean", "classify", "validate", "load", "report"):
            with self.assertRaises(SystemExit, msg=stage):
                build_parser().parse_args([stage])

    def test_classification_backend_override_is_gone(self):
        with self.assertRaises(SystemExit):
            build_parser().parse_args(["run", "--backend", "rule"])

    def test_parser_describes_the_pdf_only_flow(self):
        parser = build_parser()
        self.assertIn("PDF", parser.description)


if __name__ == "__main__":
    unittest.main()
