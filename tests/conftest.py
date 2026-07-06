"""Shared test fixtures. Points the app at a self-contained settings file so
tests never touch real services or require a populated .env."""
import os
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

_TEST_SETTINGS = """\
server:
  api_key: ""
llm:
  ollama_url: "http://localhost:11434"
  ollama_model: "qwen2.5:7b"
  num_ctx: 16384
services:
  sonarr: {url: "http://sonarr.invalid", api_key: "k"}
  radarr: {url: "http://radarr.invalid", api_key: "k"}
  emby: {url: "http://emby.invalid", api_key: "k"}
  sabnzbd: {url: "http://sab.invalid", api_key: "k"}
approvals: {}
"""


@pytest.fixture(scope="session", autouse=True)
def test_settings(tmp_path_factory):
    path = tmp_path_factory.mktemp("config") / "settings.yaml"
    path.write_text(_TEST_SETTINGS)
    os.environ["MEDIA_AGENT_CONFIG"] = str(path)
    import src.config
    src.config._settings = None
    yield path
    src.config._settings = None


@pytest.fixture(autouse=True)
def clear_pending_approvals():
    from src.tools import approval
    approval._PENDING.clear()
    yield
    approval._PENDING.clear()


class FakeToolModel:
    """Factory for a GenericFakeChatModel that tolerates bind_tools."""

    def __new__(cls, messages):
        from langchain_core.language_models.fake_chat_models import GenericFakeChatModel

        class _Fake(GenericFakeChatModel):
            def bind_tools(self, tools, **kwargs):
                return self

        return _Fake(messages=iter(messages))


@pytest.fixture
def fake_model_factory():
    return FakeToolModel
