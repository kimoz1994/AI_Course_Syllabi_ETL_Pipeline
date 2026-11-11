"""End-to-end pipeline test: raw fixture -> report, run through the CLI."""

import json
import tempfile
import unittest
from pathlib import Path

from ai_syllabi_etl.cli import main

REPO = Path(__file__).resolve().parents[1]


def _write_config(tmp: Path) -> Path:
    def q(path: Path) -> str:
        return "'" + str(path).replace("\\", "/") + "'"

    content = f"""\
input: {q(REPO / 'tests' / 'fixtures' / 'sample.csv')}
taxonomy: {q(REPO / 'taxonomy' / 'aima_taxonomy.json')}
prompt: {q(REPO / 'prompts' / 'classify_topics.md')}
paths:
  processed: {q(tmp / 'processed')}
  output: {q(tmp / 'output')}
backend: rule
validation:
  min_year: 1990
  max_year: 2030
  min_topic_coverage: 0.8
report:
  top_n_methods: 10
"""
    cfg_path = tmp / "config.yaml"
    cfg_path.write_text(content, encoding="utf-8")
    return cfg_path


class EndToEndTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls._tmpdir = tempfile.TemporaryDirectory(prefix="ai_syllabi_etl_")
        cls.tmp = Path(cls._tmpdir.name)
        cls.cfg = _write_config(cls.tmp)
        cls.exit_code = main(["run", "--config", str(cls.cfg)])

    @classmethod
    def tearDownClass(cls):
        cls._tmpdir.cleanup()

    def test_pipeline_exits_zero(self):
        self.assertEqual(self.exit_code, 0)

    def test_processed_tables_written(self):
        processed = self.tmp / "processed"
        for name in [
            "syllabi_clean.csv",
            "topic_classifications.csv",
            "syllabus_coverage_topics.csv",
            "syllabus_coverage_outcomes.csv",
            "quality_report.json",
            "syllabi.db",
        ]:
            self.assertTrue((processed / name).is_file(), name)

    def test_quality_report_is_not_failing(self):
        quality = json.loads(
            (self.tmp / "processed" / "quality_report.json").read_text(encoding="utf-8")
        )
        self.assertIn(quality["overall"], ("pass", "warn"))
        self.assertEqual(quality["row_counts"]["raw"], 5)
        self.assertEqual(quality["row_counts"]["cleaned"], 5)

    def test_report_outputs_written(self):
        out = self.tmp / "output"
        for name in [
            "report.md",
            "report_checklist.json",
            "rq1_topic_categories.html",
            "rq2_teaching_methods.html",
            "rq3_assessment_methods.html",
            "rq4_outcomes_themes.html",
            "year_trend.html",
            "rq1_topic_coverage.csv",
            "rq2_teaching_methods.csv",
            "rq3_assessment_methods.csv",
            "rq4_outcomes_themes.csv",
        ]:
            self.assertTrue((out / name).is_file(), name)

    def test_all_figure_checklists_pass(self):
        checklist = json.loads(
            (self.tmp / "output" / "report_checklist.json").read_text(encoding="utf-8")
        )
        self.assertEqual(len(checklist), 5)
        for name, entry in checklist.items():
            failed = [k for k, v in entry["checks"].items() if not v]
            self.assertEqual(failed, [], f"{name} failed checks: {failed}")

    def test_report_links_figures(self):
        text = (self.tmp / "output" / "report.md").read_text(encoding="utf-8")
        self.assertIn("rq1_topic_categories.html", text)
        self.assertIn("RQ1", text)

    def test_stage_command_extract_only(self):
        code = main(["extract", "--config", str(self.cfg)])
        self.assertEqual(code, 0)


if __name__ == "__main__":
    unittest.main()
