"""Extraction-backend seam (v1): PDF text -> schema field dict.

This is the swappable Strategy boundary that mirrors the classification
backends: implementations turn the raw text of one syllabus PDF into a
plain dict of form-field values. v1 ships the ``mock`` backend (canned
records, offline tests/CI); the ``llm`` backend (any OpenAI-compatible
server) arrives in its own ticket.
"""

from __future__ import annotations

from typing import Any

BACKENDS = ("mock",)


class ExtractionError(RuntimeError):
    """Raised when an extraction backend cannot produce a usable record."""


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


def make_extraction_backend(cfg: dict[str, Any]) -> ExtractionBackend:
    """Build the extraction backend named in the config (default: mock)."""
    name = str(cfg.get("extraction_backend", "mock"))
    if name == "mock":
        return MockExtractionBackend()
    raise ExtractionError(f"unknown extraction backend {name!r}; expected one of {BACKENDS}")
