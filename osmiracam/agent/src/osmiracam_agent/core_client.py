"""HTTP client for OsmiraCore. The station always opens the connection (ADR 0005)."""

import json
from collections.abc import AsyncIterator
from dataclasses import dataclass
from typing import Any

import httpx2

# The Core sends a keep-alive comment every 15 s on the event stream: after
# 45 s of silence the connection is considered dead and reopened.
EVENTS_READ_TIMEOUT_S = 45.0


class CoreUnavailable(Exception):
    """The Core could not be reached or gave an unusable answer."""


@dataclass(frozen=True)
class CoreEvent:
    name: str  # "state" | "select" | "config_changed"
    data: dict[str, Any]


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

    async def post_status(self, status: dict[str, Any]) -> None:
        """Report the station status (also its heartbeat)."""
        try:
            response = await self._http.post(
                f"/api/stations/{self._station_id}/status", json=status
            )
        except httpx2.HTTPError as exc:
            raise CoreUnavailable(f"cannot reach the Core: {exc!r}") from exc
        if response.status_code >= 300:
            raise CoreUnavailable(
                f"Core refused the status ({response.status_code}): {response.text[:200]}"
            )

    async def events(self) -> AsyncIterator[CoreEvent]:
        """Server-Sent Events of this station, until the connection ends.

        Raises CoreUnavailable when the connection fails or breaks.
        """
        url = f"/api/stations/{self._station_id}/events"
        timeout = httpx2.Timeout(5.0, read=EVENTS_READ_TIMEOUT_S)
        try:
            async with self._http.stream("GET", url, timeout=timeout) as response:
                if response.status_code != 200:
                    await response.aread()
                    raise CoreUnavailable(
                        f"Core answered {response.status_code} on the event stream: "
                        f"{response.text[:200]}"
                    )
                async for event in parse_sse(response.aiter_lines()):
                    yield event
        except httpx2.HTTPError as exc:
            raise CoreUnavailable(f"event stream lost: {exc!r}") from exc


async def parse_sse(lines: AsyncIterator[str]) -> AsyncIterator[CoreEvent]:
    """Minimal SSE parser: "event:" and "data:" fields, blank line ends an event,
    lines starting with ":" (keep-alive comments) are ignored."""
    name, data_lines = "message", []
    async for line in lines:
        if line == "":
            if data_lines:
                try:
                    data = json.loads("\n".join(data_lines))
                except ValueError:
                    data = None
                if isinstance(data, dict):
                    yield CoreEvent(name, data)
            name, data_lines = "message", []
        elif line.startswith(":"):
            continue
        else:
            field, _, value = line.partition(":")
            value = value.removeprefix(" ")
            if field == "event":
                name = value
            elif field == "data":
                data_lines.append(value)
