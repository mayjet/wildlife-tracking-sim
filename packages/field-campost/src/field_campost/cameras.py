from __future__ import annotations

from pathlib import Path

import numpy as np
from pydantic import BaseModel, ConfigDict, Field
from shepherd_contracts import (
    DEFAULT_MAX_OBSERVATION_DISTANCE_M,
    CameraLayout,
    CameraOrientation,
    CameraSpec,
    Position3D,
)

from field_environment import Heightmap


class FixedCameraPlacement(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, allow_inf_nan=False)

    camera_id: str = Field(min_length=1)
    x_m: float
    y_m: float
    height_above_ground_m: float = Field(gt=0.0)
    orientation: CameraOrientation
    horizontal_fov_rad: float = Field(gt=0.0)
    vertical_fov_rad: float = Field(gt=0.0)
    max_observation_distance_m: float = Field(
        default=DEFAULT_MAX_OBSERVATION_DISTANCE_M, gt=0.0
    )
    observation_interval_s: float = Field(default=1.0, gt=0.0)


def create_fixed_camera_layout(
    heightmap: Heightmap,
    placements: tuple[FixedCameraPlacement, ...] | list[FixedCameraPlacement],
    *,
    layout_id: str,
) -> CameraLayout:
    cameras = []
    for placement in placements:
        ground_z_m = heightmap.surface_elevation_at(placement.x_m, placement.y_m)
        cameras.append(
            CameraSpec(
                camera_id=placement.camera_id,
                position=Position3D(
                    x_m=placement.x_m,
                    y_m=placement.y_m,
                    z_m=ground_z_m + placement.height_above_ground_m,
                ),
                orientation=placement.orientation,
                horizontal_fov_rad=placement.horizontal_fov_rad,
                vertical_fov_rad=placement.vertical_fov_rad,
                max_observation_distance_m=placement.max_observation_distance_m,
                observation_interval_s=placement.observation_interval_s,
            )
        )
    return CameraLayout(layout_id=layout_id, cameras=tuple(cameras))


def camera_rotation_matrix(camera: CameraSpec) -> np.ndarray:
    yaw = camera.orientation.yaw_rad
    pitch = camera.orientation.pitch_rad
    roll = camera.orientation.roll_rad
    cos_yaw, sin_yaw = np.cos(yaw), np.sin(yaw)
    cos_pitch, sin_pitch = np.cos(pitch), np.sin(pitch)
    cos_roll, sin_roll = np.cos(roll), np.sin(roll)
    rotate_z = np.array(
        ((cos_yaw, -sin_yaw, 0.0), (sin_yaw, cos_yaw, 0.0), (0.0, 0.0, 1.0))
    )
    rotate_y = np.array(
        ((cos_pitch, 0.0, sin_pitch), (0.0, 1.0, 0.0), (-sin_pitch, 0.0, cos_pitch))
    )
    rotate_x = np.array(
        ((1.0, 0.0, 0.0), (0.0, cos_roll, -sin_roll), (0.0, sin_roll, cos_roll))
    )
    return rotate_z @ rotate_y @ rotate_x


def camera_forward_vector(camera: CameraSpec) -> np.ndarray:
    return camera_rotation_matrix(camera)[:, 0]


def save_camera_layout(
    layout: CameraLayout,
    path: str | Path,
    *,
    overwrite: bool = False,
) -> Path:
    destination = Path(path)
    if destination.exists() and not overwrite:
        raise FileExistsError(f"CameraLayout already exists: {destination}")
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_name(f".{destination.name}.tmp")
    temporary.write_text(layout.model_dump_json(indent=2), encoding="utf-8")
    temporary.replace(destination)
    return destination


def load_camera_layout(path: str | Path) -> CameraLayout:
    return CameraLayout.model_validate_json(Path(path).read_text(encoding="utf-8"))
