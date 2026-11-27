"""FastAPI application entry point.

Run locally: uv run uvicorn osmiracore.main:app --reload
"""

from fastapi import FastAPI

from osmiracore import __version__

app = FastAPI(title="OsmiraCore", version=__version__)


@app.get("/api/health")
def health() -> dict[str, str]:
    """Liveness check, also reports the running version."""
    return {"status": "ok", "version": __version__}
