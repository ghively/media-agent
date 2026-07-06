"""Configuration loader for Media Agent."""
import os
import re
import yaml
from pathlib import Path


def _substitute_env(value):
    """Recursively substitute ``${ENV_VAR}`` and ``${ENV_VAR:-default}``
    patterns with environment variables.

    ``${VAR:-default}`` falls back to ``default`` when VAR is unset or empty,
    so settings.yaml works out of the box without a populated .env.
    Plain ``${VAR}`` is left as-is when unset (legacy behavior).
    """
    if isinstance(value, str):
        def _sub(m):
            expr = m.group(1)
            if ":-" in expr:
                var, default = expr.split(":-", 1)
                return os.environ.get(var) or default
            return os.environ.get(expr, m.group(0))
        return re.sub(r'\$\{([^}]+)\}', _sub, value)
    elif isinstance(value, dict):
        return {k: _substitute_env(v) for k, v in value.items()}
    elif isinstance(value, list):
        return [_substitute_env(v) for v in value]
    return value


class Settings:
    """Application settings loaded from settings.yaml with env var substitution."""

    def __init__(self, config_path: str = None):
        if config_path is None:
            config_path = os.environ.get("MEDIA_AGENT_CONFIG", "config/settings.yaml")

        path = Path(config_path)
        if not path.exists():
            raise FileNotFoundError(
                f"Config file not found: {config_path}. "
                f"Copy config/settings.yaml.example to config/settings.yaml and fill in values."
            )

        with open(path) as f:
            raw = f.read()

        data: dict = yaml.safe_load(raw) or {}
        self._data: dict = _substitute_env(data)

    @property
    def server(self) -> dict:
        return self._data.get("server", {})

    @property
    def llm(self) -> dict:
        return self._data.get("llm", {})

    @property
    def sonarr(self) -> dict:
        return self._data.get("services", {}).get("sonarr", {})

    @property
    def radarr(self) -> dict:
        return self._data.get("services", {}).get("radarr", {})

    @property
    def emby(self) -> dict:
        return self._data.get("services", {}).get("emby", {})

    @property
    def sabnzbd(self) -> dict:
        return self._data.get("services", {}).get("sabnzbd", {})

    @property
    def download_station(self) -> dict:
        return self._data.get("services", {}).get("download_station", {})

    @property
    def lidarr(self) -> dict:
        return self._data.get("services", {}).get("lidarr", {})

    @property
    def bazarr(self) -> dict:
        return self._data.get("services", {}).get("bazarr", {})

    @property
    def youtube(self) -> dict:
        return self._data.get("services", {}).get("youtube", {})

    @property
    def library(self) -> dict:
        return self._data.get("library", {})

    @property
    def scheduler(self) -> dict:
        return self._data.get("scheduler", {})


def get_state_dir() -> Path:
    """Directory for persistent agent state (conversation checkpoints,
    pending approvals, audit log). Defaults to /state (the docker-compose
    volume); falls back to ./state for local development."""
    configured = os.environ.get("STATE_DIR") or \
        get_settings().server.get("state_dir", "/state")
    for candidate in (Path(configured), Path("./state")):
        try:
            candidate.mkdir(parents=True, exist_ok=True)
            probe = candidate / ".write_probe"
            probe.touch()
            probe.unlink()
            return candidate
        except OSError:
            continue
    raise OSError(f"No writable state directory (tried {configured} and ./state)")


# Singleton - loaded on first import
_settings: Settings | None = None


def get_settings() -> Settings:
    global _settings
    if _settings is None:
        _settings = Settings()
    return _settings
