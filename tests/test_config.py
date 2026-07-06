"""Tests for config loading, env substitution, and LLM option coercion."""
import os

from src.config import _substitute_env
from src.llm.client import _coerce_reasoning


def test_plain_env_var_substituted(monkeypatch):
    monkeypatch.setenv("MY_KEY", "secret")
    assert _substitute_env("${MY_KEY}") == "secret"


def test_plain_env_var_unset_left_literal():
    os.environ.pop("MISSING_VAR", None)
    assert _substitute_env("${MISSING_VAR}") == "${MISSING_VAR}"


def test_default_syntax_used_when_unset():
    os.environ.pop("MISSING_VAR", None)
    assert _substitute_env("${MISSING_VAR:-qwen2.5:7b}") == "qwen2.5:7b"


def test_default_syntax_used_when_empty(monkeypatch):
    monkeypatch.setenv("EMPTY_VAR", "")
    assert _substitute_env("${EMPTY_VAR:-fallback}") == "fallback"


def test_default_syntax_overridden_when_set(monkeypatch):
    monkeypatch.setenv("SET_VAR", "qwen3.5:9b")
    assert _substitute_env("${SET_VAR:-qwen2.5:7b}") == "qwen3.5:9b"


def test_substitution_recurses_into_nested_structures(monkeypatch):
    monkeypatch.setenv("URL", "http://x")
    data = {"a": ["${URL}"], "b": {"c": "${NOPE:-d}"}}
    assert _substitute_env(data) == {"a": ["http://x"], "b": {"c": "d"}}


def test_reasoning_coercion_matrix():
    assert _coerce_reasoning(None) is None
    assert _coerce_reasoning("") is None
    assert _coerce_reasoning("null") is None
    assert _coerce_reasoning(False) is False
    assert _coerce_reasoning(True) is True
    assert _coerce_reasoning("false") is False
    assert _coerce_reasoning("true") is True
    assert _coerce_reasoning("FALSE") is False


def test_example_settings_parse_and_resolve_defaults(monkeypatch):
    """The shipped settings.yaml.example must work with a bare environment."""
    for var in ("OLLAMA_MODEL", "OLLAMA_REASONING", "OLLAMA_NUM_CTX", "OLLAMA_URL"):
        monkeypatch.delenv(var, raising=False)
    from pathlib import Path
    import src.config as config_module
    example = Path(__file__).resolve().parent.parent / "config" / "settings.yaml.example"
    settings = config_module.Settings(str(example))
    llm = settings.llm
    assert llm["ollama_model"] == "qwen2.5:7b"
    assert int(llm["num_ctx"]) == 16384
    assert _coerce_reasoning(llm["reasoning"]) is None
    assert settings.download_station["url"].startswith("http")
