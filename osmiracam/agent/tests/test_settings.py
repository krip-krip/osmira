import socket
from pathlib import Path

import pytest

from osmiracam_agent.settings import load_settings

EXAMPLE = Path(__file__).parent.parent / "agent.toml.example"


def test_example_file_loads():
    settings = load_settings(EXAMPLE)

    assert settings.station_id == socket.gethostname()  # not set: the hostname
    assert settings.status_interval_s == 5
    assert settings.ptzview.http_port == 8081
    assert settings.ptzview.slots == 4
    assert settings.ptzview.general["hdmi_mode"] == "1920x1080@50"


def test_relative_paths_are_relative_to_the_file(tmp_path):
    (tmp_path / "agent.toml").write_text(
        'core_url = "http://core:8000/"\nstation_id = "s1"\n[ptzview]\nbinary = "bin/ptzview"\n'
    )

    settings = load_settings(tmp_path / "agent.toml")

    assert settings.core_url == "http://core:8000"
    assert settings.ptzview.binary == (tmp_path / "bin" / "ptzview").resolve()
    assert settings.state_dir == (tmp_path / "state").resolve()


def test_explicit_station_id_wins(tmp_path):
    (tmp_path / "agent.toml").write_text('core_url = "http://core"\nstation_id = "cam-op-1"\n')

    assert load_settings(tmp_path / "agent.toml").station_id == "cam-op-1"


@pytest.mark.parametrize("slots", [0, 17])
def test_slots_out_of_range_is_refused(tmp_path, slots):
    (tmp_path / "agent.toml").write_text(f'core_url = "http://core"\n[ptzview]\nslots = {slots}\n')

    with pytest.raises(ValueError, match="slots"):
        load_settings(tmp_path / "agent.toml")


def test_settings_of_other_outputs(tmp_path):
    (tmp_path / "agent.toml").write_text(
        'core_url = "http://core"\n[ptzview.output2]\nconnector = "HDMI-A-2"\n'
    )

    assert load_settings(tmp_path / "agent.toml").ptzview.outputs == {2: {"connector": "HDMI-A-2"}}
