"""Generate ptzview.conf from the station configuration.

ptzview has a fixed number of inputs (slots). Each camera keeps its input
while it stays in the configuration (assign_slots): adding, removing or
changing a camera only touches its own input. A free input has no URL, so
ptzview does not try to connect it (disabled, NO SIGNAL if shown).
"""

from osmiracam_agent.settings import PtzviewSettings
from osmiracam_agent.station_config import Camera, StationConfig

UNUSED_SLOT_URL = ""  # no URL: ptzview disables the input
DEFAULT_LATENCY_MS = 20

Assignment = list[str | None]  # camera id per input (index 0 = cam1), None = free


def assign_slots(
    config: StationConfig, slots: int, previous: Assignment | None = None
) -> Assignment:
    """Cameras keep their input; removed cameras free theirs; new cameras take
    the first free inputs, in position order. Cameras beyond the inputs are left out."""
    wanted = [c.id for c in config.cameras]
    kept: Assignment = [cid if cid in wanted else None for cid in (previous or [])[:slots]]
    kept += [None] * (slots - len(kept))
    for cid in wanted:
        if cid in kept:
            continue
        if None not in kept:
            break
        kept[kept.index(None)] = cid
    return kept


def slot_cameras(
    config: StationConfig, slots: int, assignment: Assignment | None = None
) -> list[Camera | None]:
    """Camera in each ptzview input (index 0 = cam1), None for a free input."""
    assignment = assignment or assign_slots(config, slots)
    by_id = {c.id: c for c in config.cameras}
    return [by_id.get(cid) if cid else None for cid in assignment]


def display_slot(
    config: StationConfig, slots: int, camera_id: str | None, assignment: Assignment | None = None
) -> int:
    """ptzview input to show for the camera chosen by the Core.

    Falls back to the first camera the operator may view (ADR 0009: no choice
    from the Core, or a camera that is not, or no longer, viewable here).
    """
    cameras = slot_cameras(config, slots, assignment)
    for index, camera in enumerate(cameras, start=1):
        if camera is not None and camera.view and camera.id == camera_id:
            return index
    for index, camera in enumerate(cameras, start=1):
        if camera is not None and camera.view:
            return index
    return 1


def slot_inputs(
    config: StationConfig,
    slots: int,
    assignment: Assignment | None = None,
    tag_station: bool = True,
) -> list[tuple[str, str]]:
    """(url, label) of each input, as ptzview must have them."""
    inputs = []
    for camera in slot_cameras(config, slots, assignment):
        if camera is None:
            inputs.append((UNUSED_SLOT_URL, ""))
        else:
            url = tag_streamid(camera.srt_url, config.station_id) if tag_station else camera.srt_url
            inputs.append((_one_line(url), _one_line(camera.label)))
    return inputs


def general(
    config: StationConfig, settings: PtzviewSettings, assignment: Assignment | None = None
) -> list[str]:
    """[general] settings that need a restart of ptzview when they change
    (start_camera excepted: it only matters at start)."""
    used = [c for c in slot_cameras(config, settings.slots, assignment) if c is not None]
    # ptzview has one SRT latency for all inputs: take the largest requested.
    latency = max((c.latency_ms for c in used), default=DEFAULT_LATENCY_MS)
    lines = [f"srt_latency_ms = {latency}", f"http_port = {settings.http_port}"]
    lines += [f"{key} = {_one_line(value)}" for key, value in sorted(settings.general.items())]
    return lines


def tag_streamid(url: str, station_id: str) -> str:
    """Add station=<id> to the MediaMTX streamid of an SRT URL.

    MediaMTX shows it as the "query" of the connection, so OsmiraCore can tell
    which station reads a stream even behind NAT (ADR 0010). Format:
    read:<path>[:<user>:<pass>][:<query>]. Other URLs are left untouched.
    """
    base, sep, query = url.partition("?")
    if not sep:
        return url
    parts = query.split("&")
    for index, part in enumerate(parts):
        if not part.startswith("streamid=read:"):
            continue
        value = part.removeprefix("streamid=")
        fields = value.split(":")
        tag = f"station={station_id}"
        if len(fields) == 2:  # read:cam1
            value += f":::{tag}"
        elif len(fields) == 4:  # read:cam1:user:pass
            value += f":{tag}"
        elif len(fields) >= 5 and "station=" not in fields[4]:  # existing query
            value += f"&{tag}"
        parts[index] = f"streamid={value}"
    return f"{base}?{'&'.join(parts)}"


def render(
    config: StationConfig,
    settings: PtzviewSettings,
    selected: str | None = None,
    tag_station: bool = True,
    assignment: Assignment | None = None,
) -> str:
    """ptzview.conf text; ptzview starts on the `selected` camera if possible.

    tag_station: sign the SRT connections with the station id (tag_streamid).
    """
    lines = [
        "# Generated by osmiracam-agent from the OsmiraCore configuration.",
        f"# Config version: {config.version}",
        "# Do not edit: overwritten at every configuration change.",
        "",
        "[general]",
        *general(config, settings, assignment),
        f"start_camera = {display_slot(config, settings.slots, selected, assignment)}",
    ]
    inputs = slot_inputs(config, settings.slots, assignment, tag_station)
    for index, (url, label) in enumerate(inputs, start=1):
        lines += ["", f"[cam{index}]", f"url = {url}", f"label = {label}", "tally = off"]
    return "\n".join(lines) + "\n"


def _one_line(value: str) -> str:
    # ptzview.conf is line based: a newline in a label would break the file.
    return " ".join(value.splitlines()).strip()
