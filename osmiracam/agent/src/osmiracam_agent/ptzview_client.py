"""Local HTTP API of ptzview (see osmiracam/player/README.md)."""

import httpx2


class PtzviewUnavailable(Exception):
    """ptzview did not answer (starting, restarting or stopped)."""


class PtzviewClient:
    def __init__(self, http: httpx2.AsyncClient) -> None:
        # http has base_url http://127.0.0.1:<http_port>.
        self._http = http

    async def select(self, slot: int) -> None:
        """Show ptzview input `slot` (1 = cam1) at the next refresh."""
        try:
            response = await self._http.post(f"/select/{slot}")
        except httpx2.HTTPError as exc:
            raise PtzviewUnavailable(repr(exc)) from exc
        if response.status_code != 200:
            raise PtzviewUnavailable(f"/select/{slot} answered {response.status_code}")
