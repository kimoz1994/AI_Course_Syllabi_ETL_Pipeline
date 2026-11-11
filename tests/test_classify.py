"""Unit tests for the classification stage (rule / mock / openai-parsing)."""

import json
import unittest
from pathlib import Path

import pandas as pd

from ai_syllabi_etl.classify import (
    ClassificationError,
    MockBackend,
    OpenAICompatibleBackend,
    RuleBackend,
    Taxonomy,
    _coerce_class,
    _extract_json,
    _has_keyword,
    classify_dataframe,
    coverage_table,
)
from ai_syllabi_etl.clean import clean_dataframe

REPO = Path(__file__).resolve().parents[1]
FIXTURE = REPO / "tests" / "fixtures" / "sample.csv"
TAXONOMY_PATH = REPO / "taxonomy" / "aima_taxonomy.json"
PROMPT_PATH = REPO / "prompts" / "classify_topics.md"


def _taxonomy() -> Taxonomy:
    return Taxonomy.load(TAXONOMY_PATH)


class TaxonomyTests(unittest.TestCase):
    def test_loads_seven_classes_with_other_last(self):
        tax = _taxonomy()
        self.assertEqual(len(tax.classes), 7)
        self.assertIn(7, tax.ids)
        self.assertEqual(tax.name_of[5], "Machine Learning")

    def test_prompt_block_lists_ids(self):
        block = _taxonomy().prompt_block()
        self.assertIn("1. Artificial Intelligence Foundations", block)
        self.assertIn("7. Other", block)

    def test_missing_file_raises(self):
        with self.assertRaises(ClassificationError):
            Taxonomy.load(REPO / "taxonomy" / "nope.json")


class KeywordTests(unittest.TestCase):
    def test_word_boundary_blocks_substring_matches(self):
        self.assertFalse(_has_keyword("research methods", "search"))
        self.assertTrue(_has_keyword("heuristic search techniques", "search"))

    def test_plural_tolerance(self):
        self.assertTrue(_has_keyword("decision trees and forests", "decision tree"))

    def test_symbolic_keyword(self):
        self.assertTrue(_has_keyword("a* search explained", "a*"))


class RuleBackendTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.backend = RuleBackend(_taxonomy())

    def test_problem_solving_topics(self):
        cid, conf = self.backend.score_text(
            "Uninformed and heuristic search, A* search, adversarial search, minimax"
        )
        self.assertEqual(cid, 2)
        self.assertGreater(conf, 0)

    def test_machine_learning_topics(self):
        cid, _ = self.backend.score_text(
            "Supervised learning, decision trees, neural networks, deep learning"
        )
        self.assertEqual(cid, 5)

    def test_uncertainty_topics(self):
        cid, _ = self.backend.score_text("Bayesian networks and probabilistic reasoning")
        self.assertEqual(cid, 4)

    def test_knowledge_reasoning_topics(self):
        cid, _ = self.backend.score_text("First-order logic and knowledge representation")
        self.assertEqual(cid, 3)

    def test_nlp_vision_robotics_topics(self):
        cid, _ = self.backend.score_text("Natural language processing and computer vision")
        self.assertEqual(cid, 6)

    def test_unknown_topic_falls_to_other(self):
        cid, conf = self.backend.score_text("Quantum computing and blockchain")
        self.assertEqual(cid, 7)
        self.assertEqual(conf, 0.0)


class MockBackendTests(unittest.TestCase):
    def test_canned_responses(self):
        tax = _taxonomy()
        backend = MockBackend(tax, responses={"search": 2, "bayes": 4}, default=5)
        results = backend.classify_batch(
            "S001", "course_topics", ["heuristic search", "bayes rule", "anything else"]
        )
        self.assertEqual([cid for cid, _ in results], [2, 4, 5])


class JsonParsingTests(unittest.TestCase):
    def test_extract_json_plain(self):
        obj = _extract_json('{"topics": [{"topic": "x", "class": 2}]}')
        self.assertEqual(obj["topics"][0]["class"], 2)

    def test_extract_json_from_fence_and_prose(self):
        content = 'Sure!\n```json\n{"topics": [{"topic": "x", "class": 5}]}\n```\nDone.'
        obj = _extract_json(content)
        self.assertEqual(obj["topics"][0]["class"], 5)

    def test_extract_json_no_json_raises(self):
        with self.assertRaises(ClassificationError):
            _extract_json("I could not classify these topics.")

    def test_coerce_class_variants(self):
        tax = _taxonomy()
        self.assertEqual(_coerce_class(5, tax), 5)
        self.assertEqual(_coerce_class("5", tax), 5)
        self.assertEqual(_coerce_class("5. Machine Learning", tax), 5)
        self.assertEqual(_coerce_class("Machine Learning", tax), 5)
        self.assertIsNone(_coerce_class(9, tax))
        self.assertIsNone(_coerce_class(True, tax))
        self.assertIsNone(_coerce_class("no class here", tax))


class OpenAIBackendTests(unittest.TestCase):
    def _backend(self, **overrides):
        cfg = {
            "base_url": "http://localhost:9/v1",   # unreachable on purpose
            "model": "test-model",
            "temperature": 0.0,
            "timeout_seconds": 1,
            "max_retries": 1,
            "fallback_to_rule": False,
            "api_key_env": "TEST_NO_SUCH_KEY",
        }
        cfg.update(overrides)
        return OpenAICompatibleBackend(cfg, _taxonomy(), PROMPT_PATH,
                                       rule_fallback=RuleBackend(_taxonomy()))

    def test_template_loaded_with_placeholders(self):
        backend = self._backend()
        self.assertIn("<<<TAXONOMY>>>", backend.template)
        self.assertIn("<<<TEXT>>>", backend.template)

    def test_parse_response_valid(self):
        backend = self._backend()
        content = '{"topics": [{"topic": "heuristic search", "class": 2}, {"topic": "x", "class": "Machine Learning"}]}'
        mapping = backend._parse_response(content)
        self.assertEqual(mapping["heuristic search"], 2)
        self.assertEqual(mapping["x"], 5)

    def test_parse_response_rejects_empty(self):
        backend = self._backend()
        with self.assertRaises(ClassificationError):
            backend._parse_response('{"topics": []}')

    def test_classify_batch_aligns_and_falls_back_for_skipped_items(self):
        backend = self._backend()
        backend._chat = lambda user: json.dumps(
            {"topics": [{"topic": "heuristic search", "class": 2}]}
        )
        results = backend.classify_batch(
            "S001", "course_topics", ["heuristic search", "completely different topic"]
        )
        self.assertEqual(results[0], (2, 1.0))
        # skipped item degrades to the rule backend
        self.assertEqual(results[1][0], 7)

    def test_persistent_failure_raises_without_fallback(self):
        backend = self._backend()

        def _boom(user):
            raise ConnectionError("server down")

        backend._chat = _boom
        with self.assertRaises(ClassificationError):
            backend.classify_batch("S001", "course_topics", ["heuristic search"])

    def test_persistent_failure_falls_back_to_rule_when_enabled(self):
        backend = self._backend(fallback_to_rule=True)

        def _boom(user):
            raise ConnectionError("server down")

        backend._chat = _boom
        results = backend.classify_batch("S001", "course_topics", ["heuristic search"])
        self.assertEqual(results[0][0], 2)


class PipelineHelperTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tax = _taxonomy()
        raw = pd.read_csv(FIXTURE, dtype=str)
        cls.clean, _ = clean_dataframe(raw)
        cls.class_df = classify_dataframe(cls.clean, cls.tax, RuleBackend(cls.tax))

    def test_classified_frame_schema(self):
        self.assertEqual(
            list(self.class_df.columns),
            ["syllabus_id", "field", "item_index", "topic_text",
             "class_id", "label", "backend", "confidence"],
        )
        self.assertGreater(len(self.class_df), 0)
        self.assertTrue(set(self.class_df["class_id"]).issubset(self.tax.ids))
        self.assertEqual(set(self.class_df["backend"]), {"rule"})

    def test_both_fields_classified(self):
        self.assertEqual(set(self.class_df["field"]),
                         {"course_topics", "course_outcomes"})

    def test_known_syllabus_labels(self):
        s001 = self.class_df[
            (self.class_df["syllabus_id"] == "S001")
            & (self.class_df["field"] == "course_topics")
        ]
        self.assertEqual(s001["class_id"].tolist(), [2])  # search topics

    def test_coverage_table_totals(self):
        cov = coverage_table(self.class_df, self.tax, total_syllabi=len(self.clean),
                             field="course_topics")
        self.assertEqual(len(cov), 7)
        self.assertEqual(int(cov["n_syllabi"].sum()),
                         int(self.class_df[self.class_df["field"] == "course_topics"]
                             ["syllabus_id"].nunique()))
        for pct in cov["pct_syllabi"]:
            self.assertGreaterEqual(pct, 0)
            self.assertLessEqual(pct, 100)


if __name__ == "__main__":
    unittest.main()
