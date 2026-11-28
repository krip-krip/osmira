"""Station configuration received from OsmiraCore (GET /api/stations/{id}/config),
and its local copy used when the Core is unreachable."""

import json
import logging
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class Camera:
    id: str
    label: str
    position: int
    view: bool
    srt_url: str
    latency_ms: int


@dataclass(frozen=True)
class StationConfig:
    version: str
    station_id: str
    outputs: int
    cameras: list[Camera]  # sorted by position, as sent by the Core

    @classmethod
    def from_json(cls, data: dict[str, Any]) -> "StationConfig":
        cameras = [
            Camera(
                id=c["id"],
                label=c["label"],
                position=c["position"],
                view=c["rights"]["view"],
                srt_url=c["media"]["srt_url"],
                latency_ms=c["media"]["latency_ms"],
            )
            for c in data["cameras"]
        ]
        return cls(
            version=data["version"],
            station_id=data["station"]["id"],
            outputs=data["station"].get("outputs", 1),
            cameras=sorted(cameras, key=lambda c: c.position),
        )


class ConfigStore:
    """Keeps the last configuration on disk (raw JSON from the Core)."""

    def __init__(self, state_dir: Path) -> None:
        self.path = state_dir / "config.json"

    def load(self) -> dict[str, Any] | None:
        try:
            data = json.loads(self.path.read_text())
            StationConfig.from_json(data)  # make sure it is usable
            return data
        except FileNotFoundError:
            return None
        except (ValueError, KeyError, TypeError) as exc:
            log.warning("ignoring unreadable stored config %s: %s", self.path, exc)
            return None

    def save(self, data: dict[str, Any]) -> None:
        # Write to a temporary file then rename: a power cut never leaves a
        # half-written config behind.
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps(data, indent=2, ensure_ascii=False))
        os.replace(tmp, self.path)


class SelectionStore:
    """Keeps the camera last chosen by the Core for each output, to show it
    again after a restart even if the Core is unreachable."""

    def __init__(self, state_dir: Path) -> None:
        self.path = state_dir / "selection.json"

    def load(self) -> dict[int, str | None]:
        """{output: camera id}; reads the older format (one camera = output 1)."""
        try:
            data = json.loads(self.path.read_text())
        except FileNotFoundError:
            return {}
        except ValueError as exc:
            log.warning("ignoring unreadable stored selection %s: %s", self.path, exc)
            return {}
        if not isinstance(data, dict):
            return {}
        if "outputs" not in data:  # {"camera_id": ...}, before several outputs
            camera_id = data.get("camera_id")
            return {1: camera_id} if isinstance(camera_id, str) else {}
        outputs = data["outputs"]
        if not isinstance(outputs, dict):
            return {}
        return {
            int(output): camera_id
            for output, camera_id in outputs.items()
            if output.isdigit() and (camera_id is None or isinstance(camera_id, str))
        }

    def save(self, selections: dict[int, str | None]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".tmp")
        outputs = {str(output): camera_id for output, camera_id in sorted(selections.items())}
        tmp.write_text(json.dumps({"outputs": outputs}))
        os.replace(tmp, self.path)


class SlotsStore:
    """Keeps which camera is in which ptzview input, so that a restart of the
    agent does not move the cameras around."""

    def __init__(self, state_dir: Path) -> None:
        self.path = state_dir / "slots.json"

    def load(self) -> list[str | None] | None:
        try:
            data = json.loads(self.path.read_text())
        except FileNotFoundError:
            return None
        except ValueError as exc:
            log.warning("ignoring unreadable stored slots %s: %s", self.path, exc)
            return None
        if isinstance(data, list) and all(x is None or isinstance(x, str) for x in data):
            return data
        return None

    def save(self, assignment: list[str | None]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps(assignment))
        os.replace(tmp, self.path)
