"""Tests for the configuration loader."""
import pytest

from src.config import Settings, _substitute_env


def _write(tmp_path, text):
    p = tmp_path / "settings.yaml"
    p.write_text(text)
    return str(p)


def test_env_substitution(tmp_path, monkeypatch):
    monkeypatch.setenv("MY_KEY", "secret123")
    path = _write(tmp_path, 'services:\n  sonarr:\n    api_key: "${MY_KEY}"\n')
    s = Settings(path)
    assert s.sonarr["api_key"] == "secret123"


def test_env_substitution_missing_var_left_as_is(tmp_path, monkeypatch):
    monkeypatch.delenv("NOT_SET_VAR", raising=False)
    path = _write(tmp_path, 'services:\n  sonarr:\n    api_key: "${NOT_SET_VAR}"\n')
    s = Settings(path)
    assert s.sonarr["api_key"] == "${NOT_SET_VAR}"


def test_substitute_env_nested_structures(monkeypatch):
    monkeypatch.setenv("X", "1")
    assert _substitute_env({"a": ["${X}", {"b": "${X}"}]}) == {"a": ["1", {"b": "1"}]}


def test_all_service_accessors_exist(tmp_path):
    path = _write(tmp_path, "services: {}\n")
    s = Settings(path)
    # Every accessor used by a tool module must exist and default to {}
    for name in ("sonarr", "radarr", "emby", "sabnzbd", "download_station", "youtube"):
        assert getattr(s, name) == {}
        assert s.service(name) == {}
    assert s.server == {}
    assert s.llm == {}
    assert s.scheduler == {}
    assert s.library == {}


def test_missing_config_file_raises(tmp_path):
    with pytest.raises(FileNotFoundError):
        Settings(str(tmp_path / "nope.yaml"))
