"""Unit tests for the validation stage."""

import unittest
from pathlib import Path

import pandas as pd

from ai_syllabi_etl.classify import RuleBackend, Taxonomy, classify_dataframe
from ai_syllabi_etl.clean import clean_dataframe
from ai_syllabi_etl.validate import validate

REPO = Path(__file__).resolve().parents[1]
FIXTURE = REPO / "tests" / "fixtures" / "sample.csv"

VAL_CFG = {
    "min_year": 1990,
    "max_year": 2030,
    "min_topic_coverage": 0.8,
    "required_columns": [
        "country", "institution", "year", "course_title",
        "course_topics", "teaching_methods", "assessment_methods",
    ],
}


def _pipeline_frames():
    raw = pd.read_csv(FIXTURE, dtype=str)
    clean, _ = clean_dataframe(raw)
    tax = Taxonomy.load(REPO / "taxonomy" / "aima_taxonomy.json")
    classes = classify_dataframe(clean, tax, RuleBackend(tax))
    return raw, clean, classes, tax


class ValidateTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.raw, cls.clean, cls.classes, cls.tax = _pipeline_frames()

    def _validate(self, **overrides):
        kwargs = dict(
            raw_count=len(self.raw),
            clean_df=self.clean,
            class_df=self.classes,
            taxonomy=self.tax,
            val_cfg=dict(VAL_CFG, **overrides),
        )
        return validate(**kwargs)

    def test_healthy_data_passes(self):
        report = self._validate()
        self.assertEqual(report["overall"], "pass")
        names = {c["name"]: c["status"] for c in report["checks"]}
        self.assertEqual(names["row_count_preserved"], "pass")
        self.assertEqual(names["taxonomy_labels"], "pass")
        self.assertEqual(names["duplicate_records"], "pass")
        self.assertIn("country", report["completeness_pct"])

    def test_row_loss_fails(self):
        report = validate(
            raw_count=len(self.raw) + 5,
            clean_df=self.clean,
            class_df=self.classes,
            taxonomy=self.tax,
            val_cfg=dict(VAL_CFG),
        )
        self.assertEqual(report["overall"], "fail")

    def test_missing_required_column_fails(self):
        dropped = self.clean.drop(columns=["course_topics"])
        report = validate(
            raw_count=len(self.raw),
            clean_df=dropped,
            class_df=self.classes,
            taxonomy=self.tax,
            val_cfg=dict(VAL_CFG),
        )
        names = {c["name"]: c["status"] for c in report["checks"]}
        self.assertEqual(names["required_columns"], "fail")
        self.assertEqual(report["overall"], "fail")

    def test_unknown_class_id_fails(self):
        poisoned = self.classes.copy()
        poisoned.loc[0, "class_id"] = 99
        poisoned.loc[0, "label"] = "Unknown (99)"
        report = validate(
            raw_count=len(self.raw),
            clean_df=self.clean,
            class_df=poisoned,
            taxonomy=self.tax,
            val_cfg=dict(VAL_CFG),
        )
        names = {c["name"]: c["status"] for c in report["checks"]}
        self.assertEqual(names["taxonomy_labels"], "fail")

    def test_year_outlier_warns_and_records_anomaly(self):
        outlier = self.clean.copy()
        outlier.loc[0, "year"] = 1850
        report = validate(
            raw_count=len(self.raw),
            clean_df=outlier,
            class_df=self.classes,
            taxonomy=self.tax,
            val_cfg=dict(VAL_CFG),
        )
        names = {c["name"]: c["status"] for c in report["checks"]}
        self.assertEqual(names["year_range"], "warn")
        self.assertEqual(report["overall"], "warn")
        self.assertTrue(
            any(a["type"] == "year_outlier" for a in report["anomalies"])
        )

    def test_low_topic_coverage_warns(self):
        # blank out one syllabus' topics -> coverage drops to 4/5 = 80% < 90%
        partial = self.clean.copy()
        partial.loc[0, "course_topics"] = None
        report = validate(
            raw_count=len(self.raw),
            clean_df=partial,
            class_df=self.classes,
            taxonomy=self.tax,
            val_cfg=dict(VAL_CFG, min_topic_coverage=0.9),
        )
        names = {c["name"]: c["status"] for c in report["checks"]}
        self.assertEqual(names["topic_coverage"], "warn")

    def test_duplicate_records_warn(self):
        dup = pd.concat([self.clean, self.clean.iloc[[0]]], ignore_index=True)
        report = validate(
            raw_count=len(dup),
            clean_df=dup,
            class_df=self.classes,
            taxonomy=self.tax,
            val_cfg=dict(VAL_CFG),
        )
        names = {c["name"]: c["status"] for c in report["checks"]}
        self.assertEqual(names["duplicate_records"], "warn")
        self.assertTrue(
            any(a["type"] == "duplicate_record" for a in report["anomalies"])
        )


if __name__ == "__main__":
    unittest.main()
