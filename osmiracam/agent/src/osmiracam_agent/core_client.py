"""HTTP client for OsmiraCore. The station always opens the connection (ADR 0005)."""

from typing import Any

import httpx2


class CoreUnavailable(Exception):
    """The Core could not be reached or gave an unusable answer."""


class CoreClient:
    def __init__(self, http: httpx2.AsyncClient, station_id: str) -> None:
        # http carries base_url and timeouts; tests give it a fake transport.
        self._http = http
        self._station_id = station_id

    async def fetch_config(self, known_version: str | None) -> dict[str, Any] | None:
        """New configuration, or None if it has not changed since known_version."""
        headers = {"If-None-Match": f'"{known_version}"'} if known_version else {}
        try:
            response = await self._http.get(
                f"/api/stations/{self._station_id}/config", headers=headers
            )
        except httpx2.HTTPError as exc:
            raise CoreUnavailable(f"cannot reach the Core: {exc!r}") from exc
        if response.status_code == 304:
            return None
        if response.status_code != 200:
            raise CoreUnavailable(
                f"Core answered {response.status_code} for station "
                f"'{self._station_id}': {response.text[:200]}"
            )
        try:
            return response.json()
        except ValueError as exc:
            raise CoreUnavailable("Core sent invalid JSON") from exc
