"""/api/matrix: routing matrix for the admin interface."""

from fastapi import APIRouter

from osmiracore.api.deps import SessionDep, SettingsDep
from osmiracore.schemas import Matrix
from osmiracore.services import selection
from osmiracore.services import status as heartbeat

router = APIRouter(prefix="/api/matrix", tags=["matrix"])


@router.get("")
def get_matrix(session: SessionDep, settings: SettingsDep) -> Matrix:
    """Sources (cameras) x destinations (station outputs), with current selections.

    To switch, PUT /api/stations/{station_id}/outputs/{output}/selection.
    """
    online = heartbeat.online_station_ids(session, settings.online_timeout_s)
    return selection.build_matrix(session, online)
