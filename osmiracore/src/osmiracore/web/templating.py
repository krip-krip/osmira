"""Jinja2 templates and static files of the web interface."""

from pathlib import Path

from fastapi.templating import Jinja2Templates

TEMPLATES = Jinja2Templates(directory=Path(__file__).parent / "templates")
STATIC_DIR = Path(__file__).parent / "static"


def ago(seconds: float | None) -> str:
    """12 s ago, 5 min ago, 3 h ago, 2 d ago."""
    if seconds is None:
        return "never"
    if seconds < 60:
        return f"{seconds:.0f} s ago"
    if seconds < 3600:
        return f"{seconds / 60:.0f} min ago"
    if seconds < 86400:
        return f"{seconds / 3600:.0f} h ago"
    return f"{seconds / 86400:.0f} d ago"


TEMPLATES.env.filters["ago"] = ago


def duration(seconds: float | None) -> str:
    """1 h 05 min, 12 min 30 s, 45 s."""
    if seconds is None:
        return "–"
    seconds = int(seconds)
    h, rest = divmod(seconds, 3600)
    m, s = divmod(rest, 60)
    if h:
        return f"{h} h {m:02d} min"
    if m:
        return f"{m} min {s:02d} s"
    return f"{s} s"


def num(value: float | int | None, digits: int = 1) -> str:
    """Number for tables: thousands separated, – when unknown."""
    if value is None:
        return "–"
    if isinstance(value, int):
        return f"{value:,}".replace(",", " ")
    return f"{value:,.{digits}f}".replace(",", " ")


TEMPLATES.env.filters["duration"] = duration
TEMPLATES.env.filters["num"] = num
