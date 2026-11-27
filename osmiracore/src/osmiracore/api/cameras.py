"""/api/cameras routes."""

from fastapi import APIRouter, status

from osmiracore.api.deps import BusDep, SessionDep
from osmiracore.schemas import CameraCreate, CameraOut, CameraUpdate
from osmiracore.services import cameras

router = APIRouter(prefix="/api/cameras", tags=["cameras"])


@router.get("")
def list_cameras(session: SessionDep) -> list[CameraOut]:
    return [cameras.to_out(c) for c in cameras.list_cameras(session)]


@router.post("", status_code=status.HTTP_201_CREATED)
def create_camera(data: CameraCreate, session: SessionDep, bus: BusDep) -> CameraOut:
    camera = cameras.create_camera(session, data)
    bus.sync(session)
    return cameras.to_out(camera)


@router.get("/{camera_id}")
def get_camera(camera_id: str, session: SessionDep) -> CameraOut:
    return cameras.to_out(cameras.get_camera(session, camera_id))


@router.put("/{camera_id}")
def update_camera(
    camera_id: str, data: CameraUpdate, session: SessionDep, bus: BusDep
) -> CameraOut:
    camera = cameras.update_camera(session, camera_id, data)
    bus.sync(session)
    return cameras.to_out(camera)


@router.delete("/{camera_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_camera(camera_id: str, session: SessionDep, bus: BusDep) -> None:
    """Delete a camera; station rights and selections on it go with it."""
    cameras.delete_camera(session, camera_id)
    bus.sync(session)
