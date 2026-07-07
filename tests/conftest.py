"""Shared fixtures — a test Settings object so tools never need a real config file."""
import textwrap

import pytest

import src.config as config_module
from src.config import Settings


@pytest.fixture
def test_settings(tmp_path, monkeypatch):
    """Install a minimal Settings singleton pointing at test services."""
    cfg = tmp_path / "settings.yaml"
    cfg.write_text(textwrap.dedent("""\
        server:
          host: "0.0.0.0"
          port: 8088
        llm:
          ollama_url: "http://localhost:11434"
          ollama_model: "test-model"
        services:
          sonarr:
            url: "http://sonarr.test:8989"
            api_key: "sonarr-key"
          radarr:
            url: "http://radarr.test:7878"
            api_key: "radarr-key"
          emby:
            url: "http://emby.test:8096"
            api_key: "emby-key"
          sabnzbd:
            url: "http://sab.test:8080"
            api_key: "sab-key"
    """))
    settings = Settings(str(cfg))
    monkeypatch.setattr(config_module, "_settings", settings)
    return settings
