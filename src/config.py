"""Configuration loader for Media Agent."""
import os
import re
import yaml
from pathlib import Path


def _substitute_env(value):
    """Recursively substitute ${ENV_VAR} patterns with environment variables.

    Unset vars substitute to "" — leaving the literal ``${VAR}`` in place
    would turn e.g. an unset MEDIA_AGENT_API_KEY into a real (and publicly
    known) API key, silently enabling auth with a guessable token.
    """
    if isinstance(value, str):
        return re.sub(r'\$\{([^}]+)\}', lambda m: os.environ.get(m.group(1), ""), value)
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
    def youtube(self) -> dict:
        return self._data.get("services", {}).get("youtube", {})

    @property
    def audible(self) -> dict:
        return self._data.get("services", {}).get("audible", {})

    @property
    def bandcamp(self) -> dict:
        return self._data.get("services", {}).get("bandcamp", {})

    @property
    def notifications(self) -> dict:
        return self._data.get("notifications", {})

    @property
    def roms(self) -> dict:
        return self._data.get("services", {}).get("roms", {})

    @property
    def podcasts(self) -> dict:
        return self._data.get("services", {}).get("podcasts", {})

    @property
    def twitch(self) -> dict:
        return self._data.get("services", {}).get("twitch", {})

    @property
    def komga(self) -> dict:
        return self._data.get("services", {}).get("komga", {})

    @property
    def calibre(self) -> dict:
        return self._data.get("services", {}).get("calibre", {})

    @property
    def lidarr(self) -> dict:
        return self._data.get("services", {}).get("lidarr", {})

    @property
    def prowlarr(self) -> dict:
        return self._data.get("services", {}).get("prowlarr", {})

    @property
    def qbittorrent(self) -> dict:
        return self._data.get("services", {}).get("qbittorrent", {})

    @property
    def telegram(self) -> dict:
        return self._data.get("telegram", {})

    @property
    def library(self) -> dict:
        return self._data.get("library", {})

    @property
    def scheduler(self) -> dict:
        return self._data.get("scheduler", {})

    def validate(self) -> list[str]:
        """Return warnings for config that will fail confusingly later.

        Unset ``${VAR}`` placeholders substitute to "" (see _substitute_env),
        so a missing env var surfaces as a mysterious 401 from Sonarr instead
        of a clear startup message. This names each empty credential up front.
        Warnings, not errors: services are optional and a partial deployment
        should still boot.
        """
        warnings = []
        for name in ("sonarr", "radarr", "emby", "sabnzbd"):
            svc = getattr(self, name)
            if svc.get("url") and not svc.get("api_key"):
                warnings.append(
                    f"services.{name}: url is set but api_key is empty — "
                    f"is the corresponding env var exported?")
        ds = self.download_station
        if ds.get("url") and not (ds.get("username") and ds.get("password")):
            warnings.append(
                "services.download_station: url is set but username/password "
                "are empty (DS_USERNAME / DS_PASSWORD)")
        if not self.server.get("api_key"):
            warnings.append(
                "server.api_key is empty — the /v1 API runs WITHOUT "
                "authentication (the dashboard is always open by design; "
                "both are safe only behind the loopback port bind)")
        return warnings


# Singleton - loaded on first import
_settings: Settings | None = None


def get_settings() -> Settings:
    global _settings
    if _settings is None:
        _settings = Settings()
    return _settings
