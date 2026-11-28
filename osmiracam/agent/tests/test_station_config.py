import json

from osmiracam_agent.station_config import SelectionStore


def test_selection_store_reads_the_single_output_format(tmp_path):
    (tmp_path / "selection.json").write_text(json.dumps({"camera_id": "cam2"}))

    assert SelectionStore(tmp_path).load() == {1: "cam2"}


def test_selection_store_keeps_each_output(tmp_path):
    store = SelectionStore(tmp_path)
    store.save({2: "cam1", 1: None})

    assert store.load() == {1: None, 2: "cam1"}


def test_selection_store_ignores_a_broken_file(tmp_path):
    (tmp_path / "selection.json").write_text("not json")

    assert SelectionStore(tmp_path).load() == {}
