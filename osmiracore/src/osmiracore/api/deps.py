"""Shared FastAPI dependencies."""

from typing import Annotated

from fastapi import Depends, Request
from sqlalchemy.orm import Session

from osmiracore.db import get_session
from osmiracore.services.events import EventBus
from osmiracore.services.srt import SrtCollector
from osmiracore.settings import Settings

SessionDep = Annotated[Session, Depends(get_session)]


def get_bus(request: Request) -> EventBus:
    return request.app.state.bus


# Every route that changes the database calls bus.sync(session) afterwards,
# so that connected stations hear about it.
BusDep = Annotated[EventBus, Depends(get_bus)]


def get_settings(request: Request) -> Settings:
    return request.app.state.settings


SettingsDep = Annotated[Settings, Depends(get_settings)]


def get_collector(request: Request) -> SrtCollector:
    return request.app.state.srt_collector


CollectorDep = Annotated[SrtCollector, Depends(get_collector)]
