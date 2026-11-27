"""FastAPI application entry point.

Run locally: uv run uvicorn osmiracore.main:app --reload
"""

import asyncio
import contextlib
import time
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import httpx2
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy.orm import sessionmaker

from osmiracore import __version__
from osmiracore.api import cameras, links, matrix, media_servers, srt, stations
from osmiracore.db import init_db, make_engine
from osmiracore.services.errors import ConflictError, NotFoundError
from osmiracore.services.events import EventBus
from osmiracore.services.srt import SrtCollector
from osmiracore.settings import Settings, load_settings
from osmiracore.web import admin, media
from osmiracore.web import links as links_web
from osmiracore.web import routes as web


def create_app(settings: Settings | None = None) -> FastAPI:
    """Build the application. Tests pass their own settings (temporary database)."""
    settings = settings or load_settings()

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        engine = make_engine(settings.db_path)
        init_db(engine)
        app.state.session_factory = sessionmaker(engine, expire_on_commit=False)
        app.state.bus = EventBus(asyncio.get_running_loop())
        with app.state.session_factory() as session:
            app.state.bus.sync(session)  # remember the starting state of every station
        # SRT statistics from the media servers (ADR 0010). Local servers: no proxy.
        async with httpx2.AsyncClient(timeout=3.0, trust_env=False) as http:
            app.state.http = http  # also used for live MediaMTX queries
            app.state.srt_collector = SrtCollector(
                app.state.session_factory,
                http,
                interval_s=settings.srt_interval_s,
                retention_days=settings.srt_retention_days,
            )
            stop = asyncio.Event()
            task = None
            if settings.srt_collector:
                task = asyncio.create_task(app.state.srt_collector.run(stop), name="srt")
            yield
            stop.set()
            if task is not None:
                with contextlib.suppress(asyncio.CancelledError):
                    await asyncio.wait_for(task, 5)
        engine.dispose()

    app = FastAPI(title="OsmiraCore", version=__version__, lifespan=lifespan)
    app.state.settings = settings
    app.state.started_at = time.time()  # default start of the Links period

    @app.exception_handler(NotFoundError)
    async def not_found(_request: Request, exc: NotFoundError) -> JSONResponse:
        return JSONResponse(status_code=404, content={"detail": str(exc)})

    @app.exception_handler(ConflictError)
    async def conflict(_request: Request, exc: ConflictError) -> JSONResponse:
        return JSONResponse(status_code=409, content={"detail": str(exc)})

    @app.get("/api/health")
    def health() -> dict[str, str]:
        """Liveness check, also reports the running version."""
        return {"status": "ok", "version": __version__}

    app.include_router(cameras.router)
    app.include_router(stations.router)
    app.include_router(matrix.router)
    app.include_router(media_servers.router)
    app.include_router(srt.router)
    app.include_router(links.router)
    app.include_router(web.router)
    app.include_router(admin.router)
    app.include_router(media.router)
    app.include_router(links_web.router)
    app.mount("/static", StaticFiles(directory=web.STATIC_DIR), name="static")
    return app


app = create_app()
