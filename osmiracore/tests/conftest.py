from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from osmiracore.main import create_app
from osmiracore.settings import Settings


@pytest.fixture
def client(tmp_path: Path) -> Iterator[TestClient]:
    """API client on a fresh, empty database for each test."""
    app = create_app(Settings(db_path=tmp_path / "test.db"))
    # "with" runs the app's startup (database creation) and shutdown.
    with TestClient(app) as test_client:
        yield test_client
