"""Events pushed to stations over SSE (ADR 0005).

The bus keeps, for each station, the last state it announced (config version
and selected camera per output). After every change in the database, `sync`
recomputes these states and publishes only what changed. Cascades (a deleted
camera, a removed right...) are thus announced without special cases.
"""

import asyncio
import threading
from dataclasses import dataclass, field

from sqlalchemy.orm import Session

from osmiracore.services import config, selection, stations


@dataclass(frozen=True)
class Event:
    name: str  # "config_changed" | "select" | "state"
    data: dict[str, object]


@dataclass(frozen=True)
class StationState:
    config_version: str
    # output number -> camera id (None: nothing chosen by the Core)
    selections: dict[int, str | None] = field(default_factory=dict)

    def as_event(self) -> Event:
        return Event(
            "state",
            {
                "config_version": self.config_version,
                "selections": [
                    {"output": o, "camera_id": c} for o, c in sorted(self.selections.items())
                ],
            },
        )


def station_state(session: Session, station_id: str) -> StationState:
    station = stations.get_station(session, station_id)
    return StationState(
        config_version=config.build_station_config(session, station_id).version,
        selections={s.output: s.camera_id for s in selection.output_selections(session, station)},
    )


class EventBus:
    """In-memory publish/subscribe, one queue per connected SSE client.

    Routes run in worker threads; queues belong to the event loop, so
    publishing goes through `call_soon_threadsafe`.
    """

    def __init__(self, loop: asyncio.AbstractEventLoop) -> None:
        self._loop = loop
        self._lock = threading.Lock()
        self._queues: dict[str, set[asyncio.Queue[Event]]] = {}
        self._states: dict[str, StationState] = {}

    def subscribe(self, station_id: str) -> asyncio.Queue[Event]:
        queue: asyncio.Queue[Event] = asyncio.Queue()
        with self._lock:
            self._queues.setdefault(station_id, set()).add(queue)
        return queue

    def unsubscribe(self, station_id: str, queue: asyncio.Queue[Event]) -> None:
        with self._lock:
            self._queues.get(station_id, set()).discard(queue)

    def sync(self, session: Session) -> None:
        """Publish what changed since the last sync, for every station."""
        with self._lock:
            current = {s.id: station_state(session, s.id) for s in stations.list_stations(session)}
            for station_id, new in current.items():
                old = self._states.get(station_id)
                if old is None:
                    continue  # new station: clients get the full state on connect
                if new.config_version != old.config_version:
                    self._publish(
                        station_id, Event("config_changed", {"version": new.config_version})
                    )
                for output in sorted(new.selections.keys() | old.selections.keys()):
                    camera_id = new.selections.get(output)
                    if camera_id != old.selections.get(output) and output in new.selections:
                        self._publish(
                            station_id, Event("select", {"output": output, "camera_id": camera_id})
                        )
            self._states = current

    def _publish(self, station_id: str, event: Event) -> None:
        for queue in self._queues.get(station_id, set()):
            self._loop.call_soon_threadsafe(queue.put_nowait, event)
