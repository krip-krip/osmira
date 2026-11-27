"""/api/matrix: routing matrix for the admin interface."""

from fastapi import APIRouter

from osmiracore.api.deps import SessionDep
from osmiracore.schemas import Matrix
from osmiracore.services import selection

router = APIRouter(prefix="/api/matrix", tags=["matrix"])


@router.get("")
def get_matrix(session: SessionDep) -> Matrix:
    """Sources (cameras) x destinations (station outputs), with current selections.

    To switch, PUT /api/stations/{station_id}/outputs/{output}/selection.
    """
    return selection.build_matrix(session)
