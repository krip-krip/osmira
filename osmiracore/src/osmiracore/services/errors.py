"""Errors raised by services, translated to HTTP codes by the API layer."""


class NotFoundError(Exception):
    """The requested object does not exist (HTTP 404)."""


class ConflictError(Exception):
    """The change conflicts with existing data (HTTP 409)."""
