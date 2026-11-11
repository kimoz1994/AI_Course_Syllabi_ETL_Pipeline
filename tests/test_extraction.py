"""Unit tests at the extraction-backend seam: PDF text -> field dict."""

import unittest

from ai_syllabi_etl.extraction import (
    MockExtractionBackend,
    make_extraction_backend,
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


if __name__ == "__main__":
    unittest.main()
