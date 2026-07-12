"""Shared fixtures for the media-agent test suite.

Tests run without any live services or config file: a minimal settings.yaml
is generated per-session and MEDIA_AGENT_CONFIG points at it before any
project module loads settings.
"""
import os
import sys
from pathlib import Path

import pytest

# Make `src` importable when pytest runs from the repo root.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

_TEST_CONFIG = """\
server:
  host: "127.0.0.1"
  port: 8088
  api_key: ""
llm:
  ollama_url: "http://localhost:11434"
  ollama_model: "test-model"
  temperature: 0
services:
  sonarr: {url: "http://localhost:1", api_key: "x"}
  radarr: {url: "http://localhost:1", api_key: "x"}
  emby: {url: "http://localhost:1", api_key: "x"}
  sabnzbd: {url: "http://localhost:1", api_key: "x"}
  download_station: {url: "http://localhost:1", username: "", password: ""}
  youtube: {download_path: "/tmp", subscriptions_file: "/tmp/subs.json"}
  audible: {auth_file: "/tmp/auth.json", download_path: "/tmp"}
  roms: {download_path: "/tmp", dat_path: "/tmp"}
scheduler: {enabled: false, jobs: []}
library: {media_root: "/tmp"}
"""


@pytest.fixture(scope="session", autouse=True)
def test_settings(tmp_path_factory):
    cfg = tmp_path_factory.mktemp("config") / "settings.yaml"
    cfg.write_text(_TEST_CONFIG)
    os.environ["MEDIA_AGENT_CONFIG"] = str(cfg)
    yield


@pytest.fixture(autouse=True)
def clear_router_state():
    """Reset the router's pending-selection table between tests."""
    from src.graphs import router
    router._pending.clear()
    yield
    router._pending.clear()
