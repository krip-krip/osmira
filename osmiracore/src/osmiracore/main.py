"""FastAPI application entry point.

Run locally: uv run uvicorn osmiracore.main:app --reload
"""

import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy.orm import sessionmaker

from osmiracore import __version__
from osmiracore.api import cameras, matrix, stations
from osmiracore.db import init_db, make_engine
from osmiracore.services.errors import ConflictError, NotFoundError
from osmiracore.services.events import EventBus
from osmiracore.settings import Settings, load_settings
from osmiracore.web import admin
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
        yield
        engine.dispose()

    app = FastAPI(title="OsmiraCore", version=__version__, lifespan=lifespan)
    app.state.settings = settings

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
    app.include_router(web.router)
    app.include_router(admin.router)
    app.mount("/static", StaticFiles(directory=web.STATIC_DIR), name="static")
    return app


app = create_app()
