"""Local HTTP API of ptzview (see osmiracam/player/README.md)."""

from typing import Any

import httpx2


class PtzviewUnavailable(Exception):
    """ptzview did not answer (starting, restarting or stopped)."""


class PtzviewClient:
    def __init__(self, http: httpx2.AsyncClient) -> None:
        # http has base_url http://127.0.0.1:<http_port>.
        self._http = http

    async def select(self, slot: int, output: int = 1) -> None:
        """Show ptzview input `slot` (1 = cam1) on `output` at its next refresh."""
        path = f"/select/{slot}" if output == 1 else f"/output/{output}/select/{slot}"
        try:
            response = await self._http.post(path)
        except httpx2.HTTPError as exc:
            raise PtzviewUnavailable(repr(exc)) from exc
        if response.status_code != 200:
            raise PtzviewUnavailable(f"{path} answered {response.status_code}")

    async def status(self) -> dict[str, Any]:
        """ptzview's /status: shown input, per-input stream state, system figures."""
        try:
            response = await self._http.get("/status")
            response.raise_for_status()
            return response.json()
        except (httpx2.HTTPError, ValueError) as exc:
            raise PtzviewUnavailable(repr(exc)) from exc

    async def set_input(self, slot: int, url: str, latency_ms: int) -> None:
        """New SRT URL ("" disables the input) and latency for one input; only
        that input reconnects, the others are not disturbed."""
        await self._post(f"/input/{slot}", {"url": url, "latency_ms": str(latency_ms)})

    async def set_label(self, slot: int, label: str) -> None:
        await self._post(f"/label/{slot}", {"text": label})

    async def _post(self, path: str, form: dict[str, str]) -> None:
        try:
            response = await self._http.post(path, data=form)
        except httpx2.HTTPError as exc:
            raise PtzviewUnavailable(repr(exc)) from exc
        if response.status_code != 200:
            raise PtzviewUnavailable(f"{path} answered {response.status_code}")
