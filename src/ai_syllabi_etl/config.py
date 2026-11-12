"""Configuration loading.

``config.yaml`` lives at the repository root; every relative path inside it is
resolved against the config file's own directory, so the pipeline can be run
from any working directory.
"""

from __future__ import annotations

import copy
from pathlib import Path
from typing import Any

import yaml

DEFAULTS: dict[str, Any] = {
    "input": "data/pdfs",
    "taxonomy": "taxonomy/aima_taxonomy.json",
    "prompt": "prompts/classify_topics.md",
    "paths": {
        "processed": "data/processed",
        "output": "output",
    },
    "backend": "rule",
    "extraction_backend": "mock",          # PDF flow: mock | llm
    "bloom_verbs": "prompts/bloom_verbs.txt",  # Bloom verb table (PDF flow, llm backend)
    "llm": {
        "base_url": "http://localhost:1234/v1",
        "model": "lmstudio-community/Meta-Llama-3-8B-Instruct-GGUF",
        "api_key_env": "LMSTUDIO_API_KEY",
        "temperature": 0.0,
        "timeout_seconds": 60,
        "max_retries": 3,
        "fallback_to_rule": True,
    },
    "validation": {
        "min_year": 1990,
        "max_year": 2030,
        "min_topic_coverage": 0.8,
        "required_columns": [
            "country",
            "institution",
            "year",
            "course_title",
            "course_topics",
            "teaching_methods",
            "assessment_methods",
        ],
    },
    "report": {
        "top_n_methods": 10,
    },
}

# config keys whose value is a path relative to the config file
_PATH_KEYS = ("input", "taxonomy", "prompt", "schema_contract", "bloom_verbs")
_PATH_SUBKEYS = ("processed", "output")


class ConfigError(RuntimeError):
    """Raised when the configuration file is missing or malformed."""


def _deep_merge(base: dict, override: dict) -> dict:
    merged = copy.deepcopy(base)
    for key, value in (override or {}).items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = _deep_merge(merged[key], value)
        else:
            merged[key] = copy.deepcopy(value)
    return merged


def _find_config(path: str | Path | None) -> Path:
    if path is not None:
        candidate = Path(path)
        if not candidate.is_file():
            raise ConfigError(f"config file not found: {candidate}")
        return candidate.resolve()

    cwd_candidate = Path.cwd() / "config.yaml"
    if cwd_candidate.is_file():
        return cwd_candidate.resolve()

    # repo root = two levels above src/ai_syllabi_etl/config.py
    repo_root = Path(__file__).resolve().parents[2]
    root_candidate = repo_root / "config.yaml"
    if root_candidate.is_file():
        return root_candidate.resolve()

    raise ConfigError(
        "config.yaml not found. Run from the repository root or pass --config."
    )


def _resolve(base: Path, value: str) -> str:
    p = Path(value)
    if p.is_absolute():
        return str(p)
    return str((base / p).resolve())


def load_config(path: str | Path | None = None) -> dict[str, Any]:
    """Load ``config.yaml`` merged over :data:`DEFAULTS` with paths resolved."""
    cfg_path = _find_config(path)
    try:
        with cfg_path.open(encoding="utf-8") as fh:
            data = yaml.safe_load(fh) or {}
    except yaml.YAMLError as exc:  # pragma: no cover - defensive
        raise ConfigError(f"invalid YAML in {cfg_path}: {exc}") from exc
    if not isinstance(data, dict):
        raise ConfigError(f"config root must be a mapping, got {type(data).__name__}")

    cfg = _deep_merge(DEFAULTS, data)
    base = cfg_path.parent

    for key in _PATH_KEYS:
        if key in cfg:  # optional keys (schema_contract) may be absent
            cfg[key] = _resolve(base, cfg[key])
    for key in _PATH_SUBKEYS:
        cfg["paths"][key] = _resolve(base, cfg["paths"][key])

    cfg["_config_path"] = str(cfg_path)
    cfg["_root"] = str(base)
    return cfg
