"""Links over a period: pairs of ends, totals across connections, series."""

import time
from datetime import UTC, datetime

import pytest

from osmiracore.models import SrtSample, StationSample
from osmiracore.schemas import PlayerCamera, PlayerStatus, StationStatusIn
from osmiracore.services import links
from osmiracore.services import status as heartbeat

T0 = 1_000_000.0  # fixed clock for the samples


def srt(ts, link, path, conn, packets, lost, station=None, remote=None, **extra) -> SrtSample:
    return SrtSample(
        ts=ts,
        server_id="mtx",
        link=link,
        path=path,
        camera_id=None,
        station_id=station,
        connection_id=conn,
        remote_addr=remote,
        rtt_ms=extra.get("rtt", 5.0),
        mbps=extra.get("mbps", 16.0),
        link_capacity_mbps=None,
        packets=packets,
        packets_lost=lost,
        packets_retrans=lost,
        packets_dropped=extra.get("dropped", 0),
        buffer_ms=20.0,
    )


def status(*cams: tuple[str, float, int, int]) -> StationStatusIn:
    """cams: (camera_id, fps, connects, decode_errors)."""
    return StationStatusIn(
        agent_version="0.1.0",
        player=PlayerStatus(
            running=True,
            cameras=[
                PlayerCamera(
                    camera_id=c,
                    state="streaming",
                    fps=fps,
                    mbps=16.0,
                    connects=conn,
                    decode_errors=err,
                )
                for c, fps, conn, err in cams
            ],
        ),
        system={"temp_c": 52.0, "cma_free_mb": 70},
    )


@pytest.fixture
def setup(client):
    client.post(
        "/api/media-servers", json={"id": "mtx", "label": "MediaMTX", "api_url": "http://m:9997"}
    )
    client.post("/api/stations", json={"id": "panelTest", "label": "Cadreur 1"})
    client.post(
        "/api/cameras",
        json={
            "id": "cam1",
            "label": "CAM 1",
            "media": {"source": "media_server", "media_server_id": "mtx", "path": "cam1"},
        },
    )
    client.post(
        "/api/cameras",
        json={
            "id": "cam5",
            "label": "CAM 5",
            "media": {"source": "direct", "mode": "caller", "host": "192.168.105.55", "port": 2020},
        },
    )
    factory = client.app.state.session_factory
    with factory() as session:
        session.add_all(
            [
                # camera -> server: two connections (the camera reconnected)
                srt(T0, "camera", "cam1", "A", 1000, 0),
                srt(T0 + 5, "camera", "cam1", "A", 2000, 10),
                srt(T0 + 10, "camera", "cam1", "B", 0, 0),
                srt(T0 + 15, "camera", "cam1", "B", 500, 5),
                # server -> panelTest (tagged) and an untagged reader
                srt(T0, "station", "cam1", "r1", 1000, 0, station="panelTest", rtt=4.0),
                srt(
                    T0 + 5,
                    "station",
                    "cam1",
                    "r1",
                    3000,
                    80,
                    station="panelTest",
                    rtt=8.0,
                    dropped=2,
                ),
                srt(T0 + 5, "station", "cam1", "r9", 100, 0, remote="10.0.0.9:4000"),
            ]
        )
        session.commit()
        # What panelTest reports: cam1 via mtx, cam5 direct; picture lost on cam5.
        heartbeat.record_status(
            session, "panelTest", status(("cam1", 50, 1, 0), ("cam5", 50, 1, 0)), now=T0
        )
        heartbeat.record_status(
            session, "panelTest", status(("cam1", 49, 1, 3), ("cam5", 0, 2, 0)), now=T0 + 5
        )
        heartbeat.record_status(
            session, "panelTest", status(("cam1", 50, 1, 3), ("cam5", 50, 2, 4)), now=T0 + 10
        )
    return client


def summaries(client, now: float = T0 + 20) -> dict[str, object]:
    with client.app.state.session_factory() as session:
        return {x.id: x for x in links.list_links(session, since=T0 - 1, until=T0 + 100, now=now)}


def test_one_link_per_pair_of_ends(setup):
    found = summaries(setup)

    assert sorted(found) == [
        "camera_server|mtx|cam1",
        "camera_station|cam5|panelTest",
        "server_station|mtx|cam1|?10.0.0.9",
        "server_station|mtx|cam1|panelTest",
    ]


def test_camera_to_server_adds_up_its_connections(setup):
    link = summaries(setup)["camera_server|mtx|cam1"]

    assert link.connections == 2
    assert link.packets == 1000 + 500
    assert link.packets_lost == 10 + 5
    assert link.loss_percent == 1.0
    assert link.duration_s == 15.0
    assert link.fps_avg is None  # no station on this side


def test_server_to_station_has_both_sides(setup):
    link = summaries(setup)["server_station|mtx|cam1|panelTest"]

    assert link.camera_id == "cam1"
    assert (link.packets, link.packets_lost, link.packets_dropped) == (2000, 80, 2)
    assert link.loss_percent == 4.0
    assert (link.rtt_avg_ms, link.rtt_max_ms) == (6.0, 8.0)
    assert link.fps_min == 49.0 and link.decode_errors == 3 and link.reconnects == 0


def test_direct_link_has_station_figures_only(setup):
    link = summaries(setup)["camera_station|cam5|panelTest"]

    assert link.kind == "camera_station"
    assert link.connections is None and link.loss_percent is None
    assert link.no_picture_s == 5.0  # one 5 s interval at 0 fps
    assert link.reconnects == 1
    assert link.decode_errors == 4


def test_active_and_ended_links(setup):
    late = summaries(setup, now=T0 + 1000)
    recent = summaries(setup, now=T0 + 21)  # active means seen in the last 15 s

    assert not any(x.active for x in late.values())
    assert recent["camera_station|cam5|panelTest"].active is True
    assert recent["server_station|mtx|cam1|?10.0.0.9"].active is False  # last seen at T0+5


def test_series_buckets(setup):
    with setup.app.state.session_factory() as session:
        s = links.series(
            session, "server_station|mtx|cam1|panelTest", since=T0, until=T0 + 10, points=2
        )

    assert s.bucket_s == 5.0
    assert s.t == [T0, T0 + 5, T0 + 10]
    assert s.rtt_ms == [4.0, 8.0, None]
    assert s.loss_percent == [None, 4.0, None]  # deltas start with the second sample
    assert s.retrans_per_s == [None, 16.0, None]
    assert s.fps == [50.0, 49.0, 50.0]
    assert s.decode_errors == [None, 3, 0]


def test_period_filters_the_samples(setup):
    with setup.app.state.session_factory() as session:
        found = links.list_links(session, since=T0 + 9, until=T0 + 100, now=T0 + 20)

    assert {x.id for x in found} == {
        "camera_server|mtx|cam1",
        "server_station|mtx|cam1|panelTest",
        "camera_station|cam5|panelTest",
    }


def iso(ts: float) -> str:
    return datetime.fromtimestamp(ts, UTC).isoformat().replace("+00:00", "Z")


def test_api_defaults_to_since_the_core_started(setup):
    # The samples above are from long ago: not in the default period.
    assert setup.get("/api/links").json() == []

    old = setup.get("/api/links", params={"since": iso(T0 - 1), "until": iso(T0 + 100)}).json()
    setup.post("/api/stations/panelTest/status", json=status(("cam5", 50, 1, 0)).model_dump())
    recent = setup.get("/api/links").json()

    assert len(old) == 4
    assert [x["id"] for x in recent] == ["camera_station|cam5|panelTest"]
    assert recent[0]["active"] is True


def test_api_series(setup):
    response = setup.get(
        "/api/links/series",
        params={
            "id": "camera_station|cam5|panelTest",
            "since": iso(T0),
            "until": iso(T0 + 10),
            "points": 10,
        },
    )

    body = response.json()
    assert response.status_code == 200
    assert body["fps"][:3] == [50.0, 0.0, 50.0]
    assert body["rtt_ms"][:3] == [None, None, None]  # no SRT figures for a direct link


def test_samples_are_recorded_with_each_status(client):
    client.post("/api/stations", json={"id": "panelTest", "label": "Cadreur 1"})
    client.post("/api/stations/panelTest/status", json=status(("cam9", 25, 1, 0)).model_dump())

    with client.app.state.session_factory() as session:
        rows = session.query(StationSample).order_by(StationSample.id).all()

    assert [(r.camera_id, r.fps, r.temp_c) for r in rows] == [
        (None, None, 52.0),
        ("cam9", 25.0, None),
    ]
    assert abs(rows[0].ts - time.time()) < 5
