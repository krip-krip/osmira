from conftest import core_config

from osmiracam_agent.ptzview_conf import UNUSED_SLOT_URL, render, slot_cameras
from osmiracam_agent.station_config import StationConfig


def parse(text: str) -> dict[str, dict[str, str]]:
    """Read a ptzview.conf back the way ptzview does (section -> key -> value)."""
    sections: dict[str, dict[str, str]] = {}
    current = ""
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("["):
            current = line.strip("[]")
            sections[current] = {}
        else:
            key, _, value = line.partition("=")
            sections[current][key.strip()] = value.strip()
    return sections


def test_cameras_fill_slots_in_position_order(settings):
    config = StationConfig.from_json(core_config([("cam3", 5, True), ("cam1", 2, True)]))

    conf = parse(render(config, settings.ptzview))

    assert conf["cam1"]["url"].endswith("read:cam1")
    assert conf["cam1"]["label"] == "CAM1"
    assert conf["cam2"]["url"].endswith("read:cam3")
    assert conf["cam3"]["url"] == UNUSED_SLOT_URL
    assert conf["cam4"]["url"] == UNUSED_SLOT_URL
    assert conf["cam4"]["label"] == ""


def test_general_section(settings):
    data = core_config([("cam1", 1, True), ("cam2", 2, True)])
    data["cameras"][1]["media"]["latency_ms"] = 40
    config = StationConfig.from_json(data)

    general = parse(render(config, settings.ptzview))["general"]

    assert general["srt_latency_ms"] == "40"  # one latency for all: the largest
    assert general["http_port"] == "8081"
    assert general["hdmi_mode"] == "1920x1080@50"


def test_start_on_first_viewable_camera(settings):
    config = StationConfig.from_json(core_config([("cam1", 1, False), ("cam2", 2, True)]))

    general = parse(render(config, settings.ptzview))["general"]

    assert general["start_camera"] == "2"


def test_empty_config_gives_four_free_slots(settings):
    config = StationConfig.from_json(core_config([]))

    conf = parse(render(config, settings.ptzview))

    assert [conf[f"cam{n}"]["url"] for n in range(1, 5)] == [UNUSED_SLOT_URL] * 4
    assert conf["general"]["start_camera"] == "1"
    assert conf["general"]["srt_latency_ms"] == "20"


def test_extra_cameras_are_left_out(settings):
    cameras = [(f"cam{n}", n, True) for n in range(1, 7)]
    config = StationConfig.from_json(core_config(cameras))

    slots = slot_cameras(config, 4)

    assert [c.id for c in slots if c] == ["cam1", "cam2", "cam3", "cam4"]
    assert "cam5" not in render(config, settings.ptzview)


def test_newline_in_label_cannot_break_the_file(settings):
    data = core_config([("cam1", 1, True)])
    data["cameras"][0]["label"] = "PLATEAU\n[general]\nhttp_port = 1"
    config = StationConfig.from_json(data)

    conf = parse(render(config, settings.ptzview))

    assert conf["general"]["http_port"] == "8081"
    assert conf["cam1"]["label"].startswith("PLATEAU")
