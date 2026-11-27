"""/api/cameras routes."""

from typing import Annotated

from fastapi import APIRouter, Depends, status
from sqlalchemy.orm import Session

from osmiracore.db import get_session
from osmiracore.schemas import CameraCreate, CameraOut, CameraUpdate
from osmiracore.services import cameras

router = APIRouter(prefix="/api/cameras", tags=["cameras"])

SessionDep = Annotated[Session, Depends(get_session)]


@router.get("")
def list_cameras(session: SessionDep) -> list[CameraOut]:
    return [cameras.to_out(c) for c in cameras.list_cameras(session)]


@router.post("", status_code=status.HTTP_201_CREATED)
def create_camera(data: CameraCreate, session: SessionDep) -> CameraOut:
    return cameras.to_out(cameras.create_camera(session, data))


@router.get("/{camera_id}")
def get_camera(camera_id: str, session: SessionDep) -> CameraOut:
    return cameras.to_out(cameras.get_camera(session, camera_id))


@router.put("/{camera_id}")
def update_camera(camera_id: str, data: CameraUpdate, session: SessionDep) -> CameraOut:
    return cameras.to_out(cameras.update_camera(session, camera_id, data))


@router.delete("/{camera_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_camera(camera_id: str, session: SessionDep) -> None:
    cameras.delete_camera(session, camera_id)
