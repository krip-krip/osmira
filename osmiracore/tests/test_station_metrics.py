"""Station system figures: recorded with each status, curves and summary."""

import pytest

from osmiracore.models import StationMetric
from osmiracore.schemas import PlayerCamera, PlayerStatus, StationStatusIn
from osmiracore.services import station_metrics
from osmiracore.services import status as heartbeat

T0 = 1_000_000.0


def metrics(cpu, temp, cma, uptime, throttled=0, rx=16.0, ptz_cpu=40.0) -> dict:
    return {
        "cpu_pct": cpu,
        "load1": 2.5,
        "cpu_mhz": 1800,
        "temp_c": temp,
        "throttled": throttled,
        "mem_total_mb": 905,
        "mem_available_mb": 430,
        "swap_used_mb": 0,
        "cma_total_mb": 512,
        "cma_free_mb": cma,
        "disk_used_pct": 41.5,
        "uptime_s": uptime,
        "net": {"eth0": {"rx_mbps": rx, "tx_mbps": 0.5, "rx_dropped": 1, "errors": 0}},
        "processes": {
            "ptzview": {"cpu_pct": ptz_cpu, "rss_mb": 120.0},
            "agent": {"cpu_pct": 2.0, "rss_mb": 45.0},
        },
    }


def status(m: dict, fps: float = 50.0, decode_errors: int = 0) -> StationStatusIn:
    return StationStatusIn(
        agent_version="0.1.0",
        player=PlayerStatus(
            running=True,
            cameras=[
                PlayerCamera(camera_id="cam1", fps=fps, connects=1, decode_errors=decode_errors)
            ],
        ),
        metrics=m,
    )


@pytest.fixture
def setup(client):
    client.post("/api/stations", json={"id": "panelTest", "label": "Cadreur 1"})
    with client.app.state.session_factory() as session:
        for ts, st in (
            (T0, status(metrics(30, 55.0, 40, 1000))),
            (T0 + 5, status(metrics(90, 71.0, 21, 1005, throttled=0x50005), decode_errors=3)),
            (T0 + 10, status(metrics(50, 60.0, 35, 3), fps=0.0, decode_errors=3)),  # rebooted
        ):
            heartbeat.record_status(session, "panelTest", st, now=ts)
    return client


def series(client, **kw):
    with client.app.state.session_factory() as session:
        return station_metrics.series(
            session, "panelTest", since=T0, until=T0 + 10, now=T0 + 12, **kw
        )


def test_one_row_per_status(setup):
    with setup.app.state.session_factory() as session:
        rows = session.query(StationMetric).order_by(StationMetric.ts).all()

    assert [r.cpu_pct for r in rows] == [30, 90, 50]
    assert rows[1].throttled == 0x50005 and rows[1].ptzview_rss_mb == 120.0
    assert rows[0].net["eth0"]["rx_mbps"] == 16.0


def test_curves_per_bucket(setup):
    s = series(setup, points=2)  # 5 s buckets

    assert s.t == [T0, T0 + 5, T0 + 10]
    assert s.series["cpu_pct"] == [30.0, 90.0, 50.0]
    assert s.series["temp_c"] == [55.0, 71.0, 60.0]
    assert s.series["cma_free_mb"] == [40.0, 21.0, 35.0]
    assert s.series["under_voltage"] == [0.0, 1.0, 0.0]
    assert s.series["throttled"] == [0.0, 1.0, 0.0]
    assert s.net["eth0"]["rx_mbps"] == [16.0, 16.0, 16.0]
    assert s.cameras["cam1"]["fps"] == [50.0, 50.0, 0.0]
    assert s.cameras["cam1"]["decode_errors"] == [None, 3, 0]


def test_dips_are_kept_when_buckets_are_merged(setup):
    s = series(setup, points=1)  # one 10 s bucket for T0 and T0+5, one for T0+10

    assert s.series["cma_free_mb"][0] == 21.0  # the minimum, not the average
    assert s.series["temp_c"][0] == 71.0  # the maximum


def test_summary(setup):
    summary = series(setup).summary

    assert summary == {
        "cpu_max": 90,
        "temp_max": 71.0,
        "cma_free_min": 21,
        "mem_available_min": 430,
        "under_voltage_s": 5.0,
        "throttled_s": 5.0,
        "reboots": 1,
        "samples": 3,
    }


def test_latest(setup):
    latest = series(setup).latest

    assert latest["cpu_pct"] == 50 and latest["seconds_since"] == 2.0
    assert latest["under_voltage_now"] is False and latest["since_boot"] is False


def test_station_without_figures(client):
    client.post("/api/stations", json={"id": "quiet", "label": "Quiet"})

    body = client.get("/api/stations/quiet/metrics").json()

    assert body["latest"] is None and body["summary"]["samples"] == 0


def test_api(setup):
    ok = setup.get(
        "/api/stations/panelTest/metrics",
        params={"since": "1970-01-12T13:46:40Z", "until": "1970-01-12T13:46:50Z", "points": 10},
    )

    assert ok.status_code == 200
    assert ok.json()["series"]["cpu_pct"][:3] == [30.0, 90.0, 50.0]
    assert setup.get("/api/stations/nope/metrics").status_code == 404
