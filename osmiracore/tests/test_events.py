"""SSE stream /api/stations/{id}/events.

Each test only reads events it knows were published: reading one more would
block (the stream never ends). The CI job has a timeout as a safety net.
"""

import json
from collections.abc import Iterator

import pytest

URL = "/api/stations/panelTest/events"


class EventReader:
    def __init__(self, lines: Iterator[str]) -> None:
        self._lines = lines

    def next(self) -> tuple[str, dict]:
        """Next event as (name, data), skipping keep-alive comments."""
        name, data = "", None
        for line in self._lines:
            if line.startswith("event: "):
                name = line.removeprefix("event: ")
            elif line.startswith("data: "):
                data = json.loads(line.removeprefix("data: "))
            elif line == "" and data is not None:
                return name, data
        raise AssertionError("stream closed")


@pytest.fixture
def setup(client):
    client.post("/api/stations", json={"id": "panelTest", "label": "Cadreur 1"})
    client.post("/api/stations", json={"id": "other", "label": "Cadreur 2"})
    for n in (1, 2):
        client.post(
            "/api/cameras",
            json={"id": f"cam{n}", "label": f"CAM {n}", "media": {"srt_url": "srt://m"}},
        )
    client.put(
        "/api/stations/panelTest/rights/cam1", json={"position": 1, "decode": True, "view": True}
    )
    return client


def config_version(client) -> str:
    return client.get("/api/stations/panelTest/config").json()["version"]


def select(client, camera_id: str, station: str = "panelTest"):
    url = f"/api/stations/{station}/outputs/1/selection"
    assert client.put(url, json={"camera_id": camera_id}).status_code == 200


def test_unknown_station_is_404(client):
    assert client.get("/api/stations/nope/events").status_code == 404


def test_first_event_is_the_current_state(setup):
    select(setup, "cam1")

    with setup.stream("GET", URL) as response:
        assert response.headers["content-type"].startswith("text/event-stream")
        name, data = EventReader(response.iter_lines()).next()

    assert name == "state"
    assert data == {
        "config_version": config_version(setup),
        "selections": [{"output": 1, "camera_id": "cam1"}],
    }


def test_select_event(setup):
    with setup.stream("GET", URL) as response:
        events = EventReader(response.iter_lines())
        events.next()  # state

        select(setup, "cam1")

        assert events.next() == ("select", {"output": 1, "camera_id": "cam1"})


def test_config_changed_event(setup):
    with setup.stream("GET", URL) as response:
        events = EventReader(response.iter_lines())
        events.next()  # state

        setup.put(
            "/api/stations/panelTest/rights/cam2",
            json={"position": 2, "decode": True, "view": True},
        )

        assert events.next() == ("config_changed", {"version": config_version(setup)})


def test_deleting_the_shown_camera_sends_both_events(setup):
    select(setup, "cam1")
    with setup.stream("GET", URL) as response:
        events = EventReader(response.iter_lines())
        events.next()  # state

        setup.delete("/api/cameras/cam1")

        assert events.next() == ("config_changed", {"version": config_version(setup)})
        assert events.next() == ("select", {"output": 1, "camera_id": None})


def test_other_stations_changes_are_not_sent(setup):
    setup.put("/api/stations/other/rights/cam2", json={"position": 1, "decode": True, "view": True})
    with setup.stream("GET", URL) as response:
        events = EventReader(response.iter_lines())
        events.next()  # state

        select(setup, "cam2", station="other")
        setup.put("/api/cameras/cam2", json={"label": "RENAMED", "media": {"srt_url": "srt://m"}})
        select(setup, "cam1")

        # The first event received is the one about this station.
        assert events.next() == ("select", {"output": 1, "camera_id": "cam1"})


def test_no_event_when_nothing_changes(setup):
    select(setup, "cam1")
    with setup.stream("GET", URL) as response:
        events = EventReader(response.iter_lines())
        events.next()  # state

        select(setup, "cam1")  # same camera again: no event
        setup.put("/api/stations/panelTest", json={"label": "Cadreur 1"})  # no real change
        setup.put("/api/stations/panelTest", json={"label": "Renamed"})

        assert events.next() == ("config_changed", {"version": config_version(setup)})
