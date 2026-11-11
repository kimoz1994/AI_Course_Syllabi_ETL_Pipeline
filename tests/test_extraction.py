"""Unit tests at the extraction-backend seam: PDF text -> field dict."""

import unittest
from pathlib import Path

from ai_syllabi_etl.extraction import (
    MockExtractionBackend,
    make_extraction_backend,
)
from ai_syllabi_etl.schema import (
    DEFAULT_CONTRACT_PATH,
    load_schema_contract,
    normalize_record,
    validate_record,
)

REPO = Path(__file__).resolve().parents[1]


class SchemaContractTests(unittest.TestCase):
    """The contract file's canonical values must match the form spec."""

    def test_default_contract_file_exists_at_repo_root(self):
        self.assertTrue(DEFAULT_CONTRACT_PATH.is_file())

    def test_course_level_vocabulary_matches_form_spec(self):
        contract = load_schema_contract(DEFAULT_CONTRACT_PATH)
        self.assertEqual(
            contract.vocabularies["course_level"],
            ["School", "Undergraduate", "Master", "PhD", "not mentioned", "Other/not clear"],
        )

    def test_teaching_method_vocabulary_matches_form_spec(self):
        contract = load_schema_contract(DEFAULT_CONTRACT_PATH)
        self.assertEqual(
            contract.vocabularies["teaching_method"],
            [
                "Collaborative or Group-based learning",
                "Lecture based learning",
                "Project based learning (i.e., team project)",
                "Learning using case study",
                "Flipped classroom",
                "LAB demos",
                "Seminar",
                "Workshop",
                "Online course",
                "Hybrid learning (face-to-face and online)",
                "not mentioned",
                "Other/not clear",
            ],
        )

    def test_assessment_methods_vocabulary_matches_form_spec(self):
        contract = load_schema_contract(DEFAULT_CONTRACT_PATH)
        self.assertEqual(
            contract.vocabularies["assessment_methods"],
            [
                "Short Quizzes",
                "Assignments",
                "Final Exam",
                "Midterm Exam",
                "Project",
                "Attendance or participation",
                "Presentation",
                "Report",
                "not mentioned",
                "Other/not clear",
            ],
        )

    def test_canonical_vocabularies_cover_only_the_three_closed_fields(self):
        contract = load_schema_contract(DEFAULT_CONTRACT_PATH)
        self.assertEqual(
            sorted(contract.vocabularies),
            ["assessment_methods", "course_level", "teaching_method"],
        )


def _full_record(**overrides):
    """A known-good 14-field record (all fields present, contract-valid)."""
    record = {
        "country": "Narnia",
        "institution": "Mock University",
        "year": "2023-09-01",
        "course_level": "Undergraduate",
        "target_audience": "engineering students",
        "course_title": "Introduction to Artificial Intelligence",
        "prerequisites": "Basic programming",
        "course_description": "An overview of AI.",
        "course_topics": ["Search", "Machine learning", "Ethics"],
        "course_outcomes": ["Apply search algorithms"],
        "tools": ["Python"],
        "textbooks": ["AIMA 4th ed."],
        "teaching_method": ["Lecture based learning"],
        "assessment_methods": ["Short Quizzes", "Final Exam"],
    }
    record.update(overrides)
    return record


class ValidateRecordTests(unittest.TestCase):
    def setUp(self):
        self.contract = load_schema_contract(DEFAULT_CONTRACT_PATH)

    def test_valid_record_passes_with_no_issues(self):
        self.assertEqual(validate_record(_full_record(), self.contract), [])

    def test_real_nulls_pass(self):
        record = _full_record(year=None, tools=None)
        self.assertEqual(validate_record(record, self.contract), [])

    def test_missing_field_is_reported(self):
        record = _full_record()
        del record["course_title"]
        issues = validate_record(record, self.contract)
        self.assertEqual(issues, [{"field": "course_title", "issue": "missing_field"}])

    def test_non_array_list_field_is_rejected(self):
        issues = validate_record(_full_record(course_topics="Search, ML"), self.contract)
        self.assertEqual(
            issues,
            [{"field": "course_topics", "issue": "wrong_type", "value": "Search, ML"}],
        )

    def test_non_string_text_field_is_rejected(self):
        issues = validate_record(_full_record(country=42), self.contract)
        self.assertEqual(issues, [{"field": "country", "issue": "wrong_type", "value": 42}])

    def test_non_string_list_item_is_rejected(self):
        issues = validate_record(_full_record(tools=[1, 2]), self.contract)
        self.assertEqual(len(issues), 2)
        self.assertEqual({i["issue"] for i in issues}, {"bad_item_type"})

    def test_other_not_clear_passes_as_a_distinct_label(self):
        record = _full_record(
            course_level="Other/not clear",
            teaching_method=["Other/not clear"],
            assessment_methods=["Other/not clear"],
        )
        self.assertEqual(validate_record(record, self.contract), [])

    def test_unmappable_vocabulary_value_is_reported(self):
        issues = validate_record(_full_record(course_level="Cooperative"), self.contract)
        self.assertEqual(
            issues, [{"field": "course_level", "issue": "unmapped_value", "value": "Cooperative"}]
        )

    def test_unmappable_list_value_is_reported(self):
        issues = validate_record(
            _full_record(assessment_methods=["Cooperative learning"]), self.contract
        )
        self.assertEqual(
            issues,
            [{"field": "assessment_methods", "issue": "unmapped_value",
              "value": "Cooperative learning"}],
        )

    def test_free_list_fields_accept_any_strings(self):
        record = _full_record(course_topics=["Anything", "we", "like"])
        self.assertEqual(validate_record(record, self.contract), [])


class NormalizeRecordTests(unittest.TestCase):
    def setUp(self):
        self.contract = load_schema_contract(DEFAULT_CONTRACT_PATH)

    def test_alias_map_normalizes_documented_near_variants(self):
        record, unmapped = normalize_record(
            _full_record(
                course_level="undergrad",
                teaching_method=["lecture-based", "project work"],
                assessment_methods=["quizzes", "homework", "midterm"],
            ),
            self.contract,
        )
        self.assertEqual(unmapped, [])
        self.assertEqual(record["course_level"], "Undergraduate")
        self.assertEqual(
            record["teaching_method"],
            ["Lecture based learning", "Project based learning (i.e., team project)"],
        )
        self.assertEqual(
            record["assessment_methods"], ["Short Quizzes", "Assignments", "Midterm Exam"]
        )

    def test_matching_is_case_and_whitespace_insensitive(self):
        record, unmapped = normalize_record(
            _full_record(course_level="PHD", teaching_method=["Lecture  based "]), self.contract
        )
        self.assertEqual(unmapped, [])
        self.assertEqual(record["course_level"], "PhD")
        self.assertEqual(record["teaching_method"], ["Lecture based learning"])

    def test_not_mentioned_normalizes_to_null(self):
        record, unmapped = normalize_record(
            _full_record(course_level="not mentioned"), self.contract
        )
        self.assertEqual(unmapped, [])
        self.assertIsNone(record["course_level"])

    def test_not_mentioned_list_items_are_dropped_and_emptied_list_becomes_null(self):
        record, unmapped = normalize_record(
            _full_record(teaching_method=["not mentioned", "Lecture based learning"],
                         assessment_methods=["not mentioned"]),
            self.contract,
        )
        self.assertEqual(unmapped, [])
        self.assertEqual(record["teaching_method"], ["Lecture based learning"])
        self.assertIsNone(record["assessment_methods"])

    def test_empty_strings_become_real_nulls(self):
        record, unmapped = normalize_record(
            _full_record(country="  ", tools=[]), self.contract
        )
        self.assertEqual(unmapped, [])
        self.assertIsNone(record["country"])
        self.assertIsNone(record["tools"])

    def test_unmappable_values_stay_in_record_and_are_surfaced(self):
        record, unmapped = normalize_record(
            _full_record(teaching_method=["Cooperative learning"]), self.contract
        )
        self.assertEqual(record["teaching_method"], ["Cooperative learning"])
        self.assertEqual(
            unmapped, [{"field": "teaching_method", "value": "Cooperative learning"}]
        )

    def test_duplicate_canonical_values_collapse(self):
        record, unmapped = normalize_record(
            _full_record(teaching_method=["lecture", "Lecture based learning"]), self.contract
        )
        self.assertEqual(unmapped, [])
        self.assertEqual(record["teaching_method"], ["Lecture based learning"])

    def test_missing_fields_are_not_invented(self):
        record, unmapped = normalize_record({"course_title": " X "}, self.contract)
        self.assertEqual(unmapped, [])
        self.assertEqual(record, {"course_title": "X"})

    def test_normalize_then_validate_is_the_clean_round_trip(self):
        record, unmapped = normalize_record(
            _full_record(
                course_level="masters",
                teaching_method=["seminar"],
                assessment_methods=["final"],
            ),
            self.contract,
        )
        self.assertEqual(unmapped, [])
        self.assertEqual(validate_record(record, self.contract), [])

    def test_non_list_value_in_list_field_passes_through_for_validation(self):
        record, unmapped = normalize_record(
            _full_record(course_topics="Search, ML"), self.contract
        )
        self.assertEqual(unmapped, [])
        self.assertEqual(record["course_topics"], "Search, ML")
        issues = validate_record(record, self.contract)
        self.assertEqual(
            issues,
            [{"field": "course_topics", "issue": "wrong_type", "value": "Search, ML"}],
        )


class MockBackendTests(unittest.TestCase):
    def test_factory_returns_mock_for_mock_config(self):
        backend = make_extraction_backend({"extraction_backend": "mock"})
        self.assertIsInstance(backend, MockExtractionBackend)

    def test_factory_defaults_to_mock(self):
        self.assertIsInstance(make_extraction_backend({}), MockExtractionBackend)

    def test_mock_returns_canned_field_dict(self):
        backend = MockExtractionBackend()
        record = backend.extract("any syllabus text")
        self.assertEqual(record["course_title"], "Introduction to Artificial Intelligence")
        self.assertEqual(record["country"], "Narnia")

    def test_mock_record_covers_all_form_fields(self):
        from ai_syllabi_etl.pdf_intake import FIELD_COLUMNS

        backend = MockExtractionBackend()
        record = backend.extract("any syllabus text")
        for field in FIELD_COLUMNS:
            self.assertIn(field, record)

    def test_mock_record_has_list_field(self):
        backend = MockExtractionBackend()
        record = backend.extract("any syllabus text")
        self.assertEqual(
            record["course_topics"], ["Search", "Machine learning", "Ethics"]
        )

    def test_mock_record_satisfies_the_schema_contract(self):
        from ai_syllabi_etl.schema import validate_record

        contract = load_schema_contract(DEFAULT_CONTRACT_PATH)
        backend = MockExtractionBackend()
        record = backend.extract("any syllabus text")
        self.assertEqual(validate_record(record, contract), [])


if __name__ == "__main__":
    unittest.main()
