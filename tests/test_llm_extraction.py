"""T6: the ``llm`` extraction backend (OpenAI-compatible) behind the seam.

Seams under test (the pre-agreed set):

- the extraction-backend seam: :class:`LLMExtractionBackend` against a stub
  OpenAI-compatible HTTP server on localhost (offline — no external network
  in tests or CI). Catches: the prompt contract (verbatim extraction, the
  closed vocabularies, JSON-array list fields, the Bloom verb rule with the
  semantic rule for non-English), JSON parsing + shape conformance, bounded
  retries on invalid output, and exhaustion raising ``ExtractionError``.
- the intake stage: a backend whose retries are exhausted yields an all-null
  record with a ``failed`` status + warning, and the run completes.
"""

import json
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from unittest.mock import patch

from ai_syllabi_etl import pdf_intake
from ai_syllabi_etl.extraction import (
    ExtractionError,
    LLMExtractionBackend,
    make_extraction_backend,
)
from ai_syllabi_etl.schema import DEFAULT_CONTRACT_PATH, load_schema_contract

REPO = Path(__file__).resolve().parents[1]
PDF_DIR = REPO / "tests" / "fixtures" / "pdfs"
BLOOM_PATH = REPO / "prompts" / "bloom_verbs.txt"

VALID_FIELDS = {
    "country": "Narnia",
    "institution": "Stub University",
    "year": "2024",
    "course_level": "Undergraduate",
    "target_audience": "engineering students",
    "course_title": "Introduction to Artificial Intelligence",
    "prerequisites": "Linear algebra",
    "course_description": "A first course in AI.",
    "course_topics": ["Search", "Machine learning"],
    "course_outcomes": ["describe the agent abstraction"],
    "tools": ["Python"],
    "textbooks": ["Russell & Norvig"],
    "teaching_method": ["Lecture based learning"],
    "assessment_methods": ["Final Exam"],
}


def _chat_content(**overrides) -> str:
    fields = dict(VALID_FIELDS)
    fields.update(overrides)
    return json.dumps(fields)


def _openai_response(content: str) -> dict:
    return {"choices": [{"message": {"content": content}}]}


class _StubLLMServer:
    """An offline OpenAI-compatible /chat/completions stub on 127.0.0.1:0.

    ``script`` is a list of ``(status, payload)`` pairs served in order;
    ``payload`` may be a dict (JSON-encoded) or a raw string body. Every
    request body is recorded in ``requests``.
    """

    def __init__(self, script):
        self.requests = []
        self._script = list(script)

        class Handler(BaseHTTPRequestHandler):
            def do_POST(self):
                length = int(self.headers.get("Content-Length", 0))
                body = self.rfile.read(length).decode("utf-8")
                self.server.owner.requests.append(json.loads(body))
                status, payload = self.server.owner._script.pop(0)
                data = (payload if isinstance(payload, str) else json.dumps(payload))
                raw = data.encode("utf-8")
                self.send_response(status)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(raw)))
                self.end_headers()
                self.wfile.write(raw)

            def log_message(self, *args):  # silence test output
                pass

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.server.owner = self
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()

    @property
    def base_url(self):
        host, port = self.server.server_address
        return f"http://{host}:{port}/v1"

    def stop(self):
        self.server.shutdown()
        self.server.server_close()


class LLMBackendSeamTests(unittest.TestCase):
    """The extraction-backend seam against the stub server."""

    def setUp(self):
        self.contract = load_schema_contract(DEFAULT_CONTRACT_PATH)
        # no real backoff sleeps in tests
        sleeper = patch("ai_syllabi_etl.extraction.time.sleep")
        sleeper.start()
        self.addCleanup(sleeper.stop)

    def _backend(self, server, **llm_overrides):
        llm_cfg = {
            "base_url": server.base_url,
            "model": "stub-model",
            "max_retries": 3,
            "api_key_env": "NO_SUCH_KEY",
        }
        llm_cfg.update(llm_overrides)
        return LLMExtractionBackend(llm_cfg, self.contract, BLOOM_PATH)

    def test_happy_path_returns_schema_conforming_fields(self):
        server = _StubLLMServer([(200, _openai_response(_chat_content()))])
        try:
            fields = self._backend(server).extract("some syllabus text")
        finally:
            server.stop()
        self.assertEqual(fields, VALID_FIELDS)

    def test_request_is_driven_entirely_by_config(self):
        server = _StubLLMServer([(200, _openai_response(_chat_content()))])
        try:
            self._backend(server, model="owner-model").extract("some syllabus text")
        finally:
            server.stop()
        req = server.requests[0]
        self.assertEqual(req["model"], "owner-model")
        self.assertEqual(req["temperature"], 0.0)
        messages = " ".join(m["content"] for m in req["messages"])
        self.assertIn("some syllabus text", messages)

    def test_prompt_encodes_the_extraction_contract(self):
        server = _StubLLMServer([(200, _openai_response(_chat_content()))])
        try:
            self._backend(server).extract("text")
        finally:
            server.stop()
        prompt = " ".join(
            m["content"] for m in server.requests[0]["messages"] if m["role"] == "user"
        )
        # verbatim extraction, no translation
        self.assertIn("verbatim", prompt)
        self.assertIn("never translate", prompt.lower())
        # real nulls, never sentinel words
        self.assertIn("null", prompt)
        self.assertIn("not mentioned", prompt)
        # closed vocabularies (canonical strings from the contract)
        self.assertIn("Undergraduate", prompt)
        self.assertIn("Short Quizzes", prompt)
        self.assertIn("Lecture based learning", prompt)
        self.assertIn("Other/not clear", prompt)
        # JSON-array list fields
        self.assertIn("JSON array", prompt)
        # tools inferred, no dedicated section
        self.assertIn("infer", prompt)
        # the Bloom verb rule: content not title, stem matching, semantic rule
        self.assertIn("Bloom", prompt)
        self.assertIn("analyze", prompt)
        self.assertIn("figure out", prompt)  # multi-word verb from the table
        self.assertIn("semantically", prompt)
        # the 14 keys are enumerated
        for key in VALID_FIELDS:
            self.assertIn(key, prompt)

    def test_invalid_json_is_retried(self):
        server = _StubLLMServer(
            [
                (200, _openai_response("I cannot do that.")),
                (200, _openai_response(_chat_content())),
            ]
        )
        try:
            fields = self._backend(server).extract("text")
        finally:
            server.stop()
        self.assertEqual(fields, VALID_FIELDS)
        self.assertEqual(len(server.requests), 2)

    def test_missing_or_mistyped_fields_are_retried(self):
        bad_missing = {k: v for k, v in VALID_FIELDS.items() if k != "course_title"}
        server = _StubLLMServer(
            [
                (200, _openai_response(_chat_content(course_topics="Search"))),
                (200, _openai_response(json.dumps(bad_missing))),
                (200, _openai_response(_chat_content())),
            ]
        )
        try:
            fields = self._backend(server).extract("text")
        finally:
            server.stop()
        self.assertEqual(fields, VALID_FIELDS)
        self.assertEqual(len(server.requests), 3)

    def test_http_error_is_retried(self):
        server = _StubLLMServer(
            [
                (500, {"error": "overloaded"}),
                (200, _openai_response(_chat_content())),
            ]
        )
        try:
            fields = self._backend(server).extract("text")
        finally:
            server.stop()
        self.assertEqual(fields, VALID_FIELDS)
        self.assertEqual(len(server.requests), 2)

    def test_retries_are_bounded_then_extraction_error(self):
        server = _StubLLMServer(
            [(200, _openai_response("garbage")) for _ in range(5)]
        )
        try:
            with self.assertRaises(ExtractionError) as ctx:
                self._backend(server, max_retries=3).extract("text")
        finally:
            server.stop()
        self.assertEqual(len(server.requests), 3, "exactly max_retries attempts")
        self.assertIn("3 attempts", str(ctx.exception))

    def test_factory_builds_llm_backend_from_config(self):
        backend = make_extraction_backend(
            {
                "extraction_backend": "llm",
                "llm": {"base_url": "http://127.0.0.1:1/v1", "model": "m"},
                "bloom_verbs": str(BLOOM_PATH),
                "schema_contract": str(DEFAULT_CONTRACT_PATH),
            }
        )
        self.assertIsInstance(backend, LLMExtractionBackend)
        self.assertEqual(backend.name, "llm")


class IntakeFailurePathTests(unittest.TestCase):
    """The intake seam: an exhausted backend stays visible, run completes."""

    def setUp(self):
        self.contract = load_schema_contract(DEFAULT_CONTRACT_PATH)

    def test_failed_files_yield_all_null_records_with_a_warning(self):
        records, log = pdf_intake.intake(PDF_DIR, _FailingBackend(), self.contract)
        by_file = {e["source_file"]: e for e in log["records"]}
        for name in ("alpha_syllabus.pdf", "bravo_syllabus.pdf"):
            record = next(r for r in records if r["source_file"] == name)
            entry = by_file[name]
            self.assertEqual(entry["status"], "failed")
            self.assertEqual(entry["warnings"], [_FailingBackend.ERR])
            self.assertTrue(
                all(record[k] is None for k in VALID_FIELDS),
                f"{name}: failed extraction must yield an all-null record",
            )

    def test_failed_entries_are_not_cached_as_successes(self):
        _, log = pdf_intake.intake(PDF_DIR, _FailingBackend(), self.contract)
        backend2 = _RecordingBackend()
        _, log2 = pdf_intake.intake(
            PDF_DIR, backend2, self.contract, previous_log=log
        )
        self.assertEqual(backend2.calls, 2, "failed entries must be retried")
        self.assertEqual(
            {e["cache"] for e in log2["records"]}, {"miss"}
        )


class _FailingBackend:
    """Stub that always raises: retries exhausted at the backend."""

    name = "failing"
    ERR = "LLM extraction failed after 3 attempts: bad JSON"

    def extract(self, text, source=None):
        raise ExtractionError(self.ERR)


class _RecordingBackend:
    """Minimal counting stub for the cache-visibility assertion above."""

    name = "recording"
    calls = 0

    def extract(self, text, source=None):
        self.calls += 1
        raise ExtractionError(_FailingBackend.ERR)


if __name__ == "__main__":
    unittest.main()
