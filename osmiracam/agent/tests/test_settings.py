from pathlib import Path

from osmiracam_agent.settings import load_settings

EXAMPLE = Path(__file__).parent.parent / "agent.toml.example"


def test_example_file_loads():
    settings = load_settings(EXAMPLE)

    assert settings.station_id == "panelTest"
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
