"""Unit tests for the cleaning stage."""

import unittest
from pathlib import Path

import pandas as pd

from ai_syllabi_etl.clean import (
    clean_dataframe,
    clean_text,
    is_sentinel,
    normalize_header,
    parse_year,
    split_items,
    split_outcomes,
    split_topic_items,
    standardize_columns,
)

FIXTURE = Path(__file__).parent / "fixtures" / "sample.csv"


class HeaderTests(unittest.TestCase):
    def test_normalize_header_strips_spacing_and_question_mark(self):
        self.assertEqual(normalize_header("Which country ? "), "which country")
        self.assertEqual(normalize_header("Year ? "), "year")
        self.assertEqual(normalize_header("What is the course  content/topics?"),
                         "what is the course content/topics")

    def test_standardize_columns_renames_all_raw_headers(self):
        raw = pd.read_csv(FIXTURE, dtype=str)
        renamed, _log = standardize_columns(raw)
        expected = {
            "country", "institution", "year", "course_title", "prerequisites",
            "course_description", "course_topics", "course_outcomes", "tools",
            "textbooks", "teaching_methods", "assessment_methods",
        }
        self.assertEqual(set(renamed.columns), expected)

    def test_fallback_header_for_unknown_columns(self):
        df = pd.DataFrame({"Totally New Field ?": ["x"]})
        renamed, log = standardize_columns(df)
        self.assertEqual(renamed.columns[0], "totally_new_field")
        self.assertEqual(log[0]["rule"], "fallback_header")


class CellCleaningTests(unittest.TestCase):
    def test_sentinels_are_detected(self):
        for value in ["not mentioned", " N/A ", "none", "-", "", None, float("nan")]:
            self.assertTrue(is_sentinel(value), value)
        self.assertFalse(is_sentinel("real content"))

    def test_clean_text_collapses_whitespace_but_keeps_newlines(self):
        self.assertEqual(clean_text("a  b\tc"), "a b c")
        self.assertEqual(clean_text("1. first\n\n2. second"), "1. first\n\n2. second")
        self.assertIsNone(clean_text("not mentioned"))
        self.assertIsNone(clean_text("   "))

    def test_parse_year_variants(self):
        self.assertEqual(parse_year("2018-01-01"), 2018)
        self.assertEqual(parse_year("2022"), 2022)
        self.assertEqual(parse_year("c. 2015 edition"), 2015)
        self.assertIsNone(parse_year("not mentioned"))
        self.assertIsNone(parse_year("spring semester"))
        self.assertIsNone(parse_year("1850"))  # outside 1900-2100 sanity band

    def test_split_items_on_semicolon(self):
        self.assertEqual(split_items("Short Quizes;Final Exam"),
                         ["Short Quizes", "Final Exam"])
        self.assertEqual(split_items(None), [])

    def test_split_outcomes_strips_numbering(self):
        items = split_outcomes("1. Understand search\n2. Understand planning\n")
        self.assertEqual(items, ["Understand search", "Understand planning"])

    def test_split_topic_items_strips_bullets_but_not_commas(self):
        items = split_topic_items("History of AI\n○ Course structure\n- Setup of tools")
        self.assertEqual(items, ["History of AI", "Course structure", "Setup of tools"])
        # commas must not split topic phrases
        self.assertEqual(split_topic_items("Search, A* and planning"),
                         ["Search, A* and planning"])


class CleanDataframeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        raw = pd.read_csv(FIXTURE, dtype=str)
        cls.raw = raw
        cls.clean, cls.log = clean_dataframe(raw)

    def test_row_count_and_ids_preserved(self):
        self.assertEqual(len(self.clean), len(self.raw))
        self.assertEqual(self.clean["syllabus_id"].tolist(),
                         ["S001", "S002", "S003", "S004", "S005"])
        self.assertTrue(self.clean["syllabus_id"].is_unique)

    def test_year_parsed_to_int64(self):
        self.assertEqual(self.clean["year"].tolist()[:4], [2018, 2022, 2020, 2019])
        self.assertTrue(pd.isna(self.clean["year"].iloc[4]))  # 'not mentioned'

    def test_sentinels_converted_to_missing(self):
        row5 = self.clean.iloc[4]
        self.assertTrue(pd.isna(row5["teaching_methods"]))
        self.assertTrue(pd.isna(row5["assessment_methods"]))
        self.assertTrue(pd.isna(self.clean.iloc[1]["course_description"]))
        # real content survives
        self.assertEqual(self.clean.iloc[0]["institution"], "MIT")

    def test_cleaning_log_records_sentinel_rules(self):
        rules = {(e["rule"], e["column"]) for e in self.log}
        self.assertIn(("sentinel_to_missing", "teaching_methods"), rules)
        self.assertIn(("assign_id", "-"), rules)


if __name__ == "__main__":
    unittest.main()
