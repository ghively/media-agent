"""Shared async client for *arr services (Sonarr/Radarr v3 API)."""
import httpx


class ArrClient:
    """Async client for the Sonarr/Radarr v3 API."""

    def __init__(self, base_url: str, api_key: str, timeout: int = 30):
        self.base_url = base_url.rstrip("/")
        self.headers = {"X-Api-Key": api_key}
        self.timeout = timeout

    async def _get(self, endpoint: str, params: dict | None = None):
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            resp = await client.get(
                f"{self.base_url}/api/v3{endpoint}", headers=self.headers, params=params
            )
            resp.raise_for_status()
            return resp.json()

    async def _post(self, endpoint: str, json_data: dict):
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            resp = await client.post(
                f"{self.base_url}/api/v3{endpoint}", headers=self.headers, json=json_data
            )
            resp.raise_for_status()
            return resp.json()
