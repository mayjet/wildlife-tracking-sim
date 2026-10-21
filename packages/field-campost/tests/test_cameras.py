from math import isclose

import numpy as np
import pytest
from shepherd_contracts import CameraOrientation

from field_campost import (
    FixedCameraPlacement,
    camera_forward_vector,
    create_fixed_camera_layout,
    load_camera_layout,
    save_camera_layout,
)


def test_fixed_camera_height_is_relative_to_terrain(environment_case, camera_layout):
    camera = camera_layout.cameras[0]
    ground = environment_case.heightmap.elevation_at(camera.position.x_m, camera.position.y_m)

    assert isclose(camera.position.z_m, ground + 3.0)


def test_fixed_camera_rejects_position_outside_terrain(environment_case):
    placement = FixedCameraPlacement(
        camera_id="outside",
        x_m=-1.0,
        y_m=5.0,
        height_above_ground_m=3.0,
        orientation=CameraOrientation(yaw_rad=0.0, pitch_rad=0.0, roll_rad=0.0),
        horizontal_fov_rad=1.0,
        vertical_fov_rad=0.8,
    )

    with pytest.raises(IndexError):
        create_fixed_camera_layout(environment_case.heightmap, [placement], layout_id="invalid")


def test_camera_layout_json_round_trip(tmp_path, camera_layout):
    path = save_camera_layout(camera_layout, tmp_path / "camera_layout.json")

    assert load_camera_layout(path) == camera_layout
    with pytest.raises(FileExistsError):
        save_camera_layout(camera_layout, path)


def test_camera_forward_vector_uses_contract_yaw_pitch(camera_layout):
    camera = camera_layout.cameras[0]
    direction = camera_forward_vector(camera)

    assert np.isclose(np.linalg.norm(direction), 1.0)
    assert direction[2] < 0.0
