"""Extraction-backend seam (v1): PDF text -> schema field dict.

This is the swappable Strategy boundary that mirrors the classification
backends: implementations turn the raw text of one syllabus PDF into a
plain dict of form-field values. v1 ships the ``mock`` backend (canned
records, offline tests/CI) and the ``llm`` backend (any OpenAI-compatible
chat server — LM Studio, Ollama, vLLM, or a cloud API; endpoint, model and
run parameters are config, not code). The extraction prompt encodes the
schema contract: verbatim extraction with no translation, real nulls, the
closed vocabularies, JSON-array list fields, and the owner's Bloom-verb
rule for outcome collection. Invalid LLM output is retried a bounded
number of times; exhaustion raises :class:`ExtractionError`, which the
intake stage turns into an all-null record plus a warning so the run
completes and the failure stays visible.
"""

from __future__ import annotations

import json
import os
import re
import textwrap
import time
from pathlib import Path
from typing import Any

import requests

from .schema import (
    DEFAULT_CONTRACT_PATH,
    FIELD_COLUMNS,
    LIST_FIELDS,
    NOT_MENTIONED,
    SchemaContract,
    load_schema_contract,
)

BACKENDS = ("mock", "llm")

# Single-value fields: a string or null. Everything in FIELD_COLUMNS that is
# not a LIST_FIELDS member.
SCALAR_FIELDS = tuple(f for f in FIELD_COLUMNS if f not in LIST_FIELDS)

_PROMPT_TEMPLATE = """You extract structured fields from one university course syllabus.

OUTPUT: reply with ONLY a JSON object — no prose, no markdown fences — with
exactly these 14 keys: {field_keys}

TYPES:
- Single-value fields ({scalar_keys}): a string or null.
- List fields ({list_keys}): a JSON array of strings, or null.
- year: the teaching year exactly as the syllabus states it (e.g. "2024" or
  "January 15, 2024").

EXTRACTION RULES:
1. Copy every value verbatim from the syllabus text. Never translate,
   summarize or rephrase — even when the text is not in English.
2. When the syllabus does not state a field, use null. Never write
   placeholder words such as "not mentioned", "none" or "n/a".
3. course_topics and textbooks: list every item exactly as written. No
   distinction is made between a main textbook and secondary textbooks.
4. course_level MUST be one of: {course_level_values} — or null when the
   syllabus does not state a level.
5. teaching_method (sometimes titled "course format") values MUST be chosen
   from: {teaching_method_values} — or null when none apply.
6. assessment_methods values MUST be chosen from: {assessment_methods_values}
   — or null when none apply.
7. tools: the hardware/software tools students use in the course. There is
   no dedicated section for them: infer them from every other section
   (prerequisites, description, topics, policies), collecting tool names
   verbatim (languages, libraries, frameworks, lab equipment).
8. course_outcomes — the Bloom verb rule:
   - Identify outcome statements by content, not by section title: titles
     vary ("Outcomes", "Objectives", "Learning Goals", ...), so a heading
     is a hint only, never the deciding signal.
   - Collect a line ONLY if it starts with or contains one of these Bloom's
     Taxonomy verbs, matched case-insensitively on the verb stem — any
     inflection sharing the stem counts (analyze → analyzes, analyzed,
     analyzing; construct → constructs, constructing; design → designs,
     designed, designing):
       {bloom_verbs}
   - A line with no Bloom verb from this list is NOT collected. Do not
     confuse course outcomes with general course objectives: the Bloom
     verb is the discriminator.
   - For non-English text, apply the rule semantically: collect lines that
     contain verb equivalents of the listed verbs in any language, with the
     English verb list as the backstop. Still copy collected lines
     verbatim, never translated.

SYLLABUS TEXT:
<<<TEXT>>>
"""


class ExtractionError(RuntimeError):
    """Raised when an extraction backend cannot produce a usable record."""


def _extract_json(content: str) -> dict[str, Any]:
    """Pull the first usable JSON object out of an LLM response."""
    candidates: list[str] = []
    fence = re.search(r"```(?:json)?\s*(.*?)```", content, re.S)
    if fence:
        candidates.append(fence.group(1))
    start, end = content.find("{"), content.rfind("}")
    if start != -1 and end > start:
        candidates.append(content[start : end + 1])
    for candidate in candidates:
        try:
            obj = json.loads(candidate)
        except json.JSONDecodeError:
            continue
        if isinstance(obj, dict):
            return obj
    raise ExtractionError("no JSON object found in LLM response")


class ExtractionBackend:
    """Base class: subclasses implement :meth:`extract`."""

    name = "base"

    def extract(self, text: str, source: dict[str, Any] | None = None) -> dict[str, Any]:
        raise NotImplementedError


class MockExtractionBackend(ExtractionBackend):
    """Deterministic canned records for offline tests and CI."""

    name = "mock"

    def extract(self, text: str, source: dict[str, Any] | None = None) -> dict[str, Any]:
        return {
            "country": "Narnia",
            "institution": "Mock University",
            "year": None,
            "course_level": None,
            "target_audience": None,
            "course_title": "Introduction to Artificial Intelligence",
            "prerequisites": None,
            "course_description": None,
            "course_topics": ["Search", "Machine learning", "Ethics"],
            "course_outcomes": None,
            "tools": None,
            "textbooks": None,
            "teaching_method": None,
            "assessment_methods": None,
        }


class LLMExtractionBackend(ExtractionBackend):
    """Provider-agnostic extraction backend (OpenAI chat-completions).

    Talks to any OpenAI-compatible server; endpoint, model name, sampling
    parameters, timeout, retries and API-key environment variable are all
    config (the ``llm`` block), never code. The extraction prompt is built
    once from the schema contract (closed vocabularies) and the owner's
    Bloom verb table. Invalid or non-conforming output (no JSON, missing
    keys, wrong types, HTTP errors) is retried up to ``max_retries``
    times; exhaustion raises :class:`ExtractionError`.
    """

    name = "llm"

    def __init__(
        self,
        llm_cfg: dict[str, Any],
        contract: SchemaContract,
        bloom_verbs_path: str | Path,
    ):
        self.base_url = str(llm_cfg.get("base_url", "http://localhost:1234/v1")).rstrip("/")
        self.model = str(llm_cfg.get("model", ""))
        self.temperature = float(llm_cfg.get("temperature", 0.0))
        self.timeout = float(llm_cfg.get("timeout_seconds", 60))
        self.max_retries = max(1, int(llm_cfg.get("max_retries", 3)))
        self.api_key = os.environ.get(str(llm_cfg.get("api_key_env", "")), "") or "local"
        self.contract = contract

        verbs = _load_bloom_verbs(bloom_verbs_path)
        vocab = {
            field: [v for v in contract.vocabularies[field] if v != NOT_MENTIONED]
            for field in ("course_level", "teaching_method", "assessment_methods")
        }
        self._prompt_template = _PROMPT_TEMPLATE.format(
            field_keys=", ".join(FIELD_COLUMNS),
            scalar_keys=", ".join(SCALAR_FIELDS),
            list_keys=", ".join(sorted(LIST_FIELDS)),
            course_level_values=", ".join(vocab["course_level"]),
            teaching_method_values=", ".join(vocab["teaching_method"]),
            assessment_methods_values=", ".join(vocab["assessment_methods"]),
            bloom_verbs=textwrap.fill(
                ", ".join(verbs), width=78, subsequent_indent="       "
            ),
        )

    # -- transport ---------------------------------------------------------
    def _chat(self, user_content: str) -> str:
        url = f"{self.base_url}/chat/completions"
        payload = {
            "model": self.model,
            "temperature": self.temperature,
            "messages": [
                {
                    "role": "system",
                    "content": "You extract structured fields from course syllabi. "
                    "Return only the requested JSON.",
                },
                {"role": "user", "content": user_content},
            ],
        }
        headers = {"Authorization": f"Bearer {self.api_key}"}
        response = requests.post(
            url, json=payload, headers=headers, timeout=self.timeout
        )
        response.raise_for_status()
        data = response.json()
        return data["choices"][0]["message"]["content"]

    # -- conformance -------------------------------------------------------
    def _parse_fields(self, content: str) -> dict[str, Any]:
        """Parse + shape-check the response into a plain field dict.

        Shape conformance only: all 14 keys present, scalars are strings
        or null, list fields are string arrays. Vocabulary canonicalization
        is the seam's alias-map job (schema.normalize_record), not a retry
        condition.
        """
        fields = _extract_json(content)
        missing = [f for f in FIELD_COLUMNS if f not in fields]
        if missing:
            raise ExtractionError(f"LLM response missing fields: {missing}")
        for field in SCALAR_FIELDS:
            value = fields[field]
            if value is not None and not isinstance(value, str):
                raise ExtractionError(
                    f"LLM response field {field!r} must be a string or null, "
                    f"got {type(value).__name__}"
                )
        for field in sorted(LIST_FIELDS):
            value = fields[field]
            if value is None:
                continue
            if not isinstance(value, list) or not all(
                isinstance(item, str) for item in value
            ):
                raise ExtractionError(
                    f"LLM response field {field!r} must be a JSON array of strings or null"
                )
        return {field: fields[field] for field in FIELD_COLUMNS}

    # -- public ------------------------------------------------------------
    def extract(self, text: str, source: dict[str, Any] | None = None) -> dict[str, Any]:
        user_content = self._prompt_template.replace("<<<TEXT>>>", text)
        last_error: Exception | None = None
        for attempt in range(1, self.max_retries + 1):
            try:
                return self._parse_fields(self._chat(user_content))
            except Exception as exc:  # network, HTTP, or non-conforming output
                last_error = exc
                if attempt < self.max_retries:
                    time.sleep(2 ** (attempt - 1))
        raise ExtractionError(
            f"LLM extraction failed after {self.max_retries} attempts: {last_error}"
        )


def _load_bloom_verbs(path: str | Path) -> list[str]:
    """Load the owner's Bloom verb table (one verb per line)."""
    p = Path(path)
    if not p.is_file():
        raise ExtractionError(f"Bloom verb table not found: {p}")
    verbs = [line.strip().lower() for line in p.read_text(encoding="utf-8").splitlines()]
    return [v for v in verbs if v]


def make_extraction_backend(cfg: dict[str, Any]) -> ExtractionBackend:
    """Build the extraction backend named in the config (default: mock)."""
    name = str(cfg.get("extraction_backend", "mock"))
    if name == "mock":
        return MockExtractionBackend()
    if name == "llm":
        contract = load_schema_contract(cfg.get("schema_contract") or DEFAULT_CONTRACT_PATH)
        return LLMExtractionBackend(
            cfg.get("llm", {}),
            contract,
            cfg.get("bloom_verbs", "prompts/bloom_verbs.txt"),
        )
    raise ExtractionError(f"unknown extraction backend {name!r}; expected one of {BACKENDS}")
