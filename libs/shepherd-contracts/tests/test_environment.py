from __future__ import annotations

from math import pi

import pytest
from pydantic import ValidationError

from shepherd_contracts import (
    DEFAULT_MAX_OBSERVATION_DISTANCE_M,
    CameraLayout,
    CameraOrientation,
    CameraSpec,
    CaseSpec,
    LocalCoordinateSystem,
    ObservationPointLayout,
    ObservationPointSpec,
    Position3D,
)


def test_public_types_are_importable(case_spec: CaseSpec) -> None:
    assert case_spec.case_id == "farm-a"


def test_case_spec_json_round_trip(case_spec: CaseSpec) -> None:
    restored = CaseSpec.model_validate_json(case_spec.model_dump_json())
    assert restored == case_spec


def test_case_reference_must_be_relative(case_spec: CaseSpec) -> None:
    payload = case_spec.model_dump()
    payload["environment"]["terrain"] = "../terrain.tif"
    with pytest.raises(ValidationError):
        CaseSpec.model_validate(payload)


def test_coordinate_axes_must_be_perpendicular() -> None:
    with pytest.raises(ValidationError):
        LocalCoordinateSystem(
            name="invalid",
            x_axis="EAST",
            y_axis="WEST",
            origin_description="origin",
            vertical_datum="local",
        )


def test_coordinates_reject_non_finite_values() -> None:
    with pytest.raises(ValidationError):
        Position3D(x_m=float("inf"), y_m=0.0, z_m=0.0)


def test_camera_requires_explicit_observation_distance() -> None:
    assert DEFAULT_MAX_OBSERVATION_DISTANCE_M == 42.0
    with pytest.raises(ValidationError):
        CameraSpec(
            camera_id="cam-1",
            position=Position3D(x_m=0.0, y_m=0.0, z_m=3.0),
            orientation=CameraOrientation(yaw_rad=0.0, pitch_rad=0.0, roll_rad=0.0),
            horizontal_fov_rad=pi / 2.0,
            vertical_fov_rad=pi / 3.0,
            observation_interval_s=1.0,
        )


def test_camera_layout_rejects_duplicate_ids() -> None:
    camera = CameraSpec(
        camera_id="cam-1",
        position=Position3D(x_m=0.0, y_m=0.0, z_m=3.0),
        orientation=CameraOrientation(yaw_rad=0.0, pitch_rad=0.0, roll_rad=0.0),
        horizontal_fov_rad=pi / 2.0,
        vertical_fov_rad=pi / 3.0,
        max_observation_distance_m=DEFAULT_MAX_OBSERVATION_DISTANCE_M,
        observation_interval_s=1.0,
    )
    with pytest.raises(ValidationError):
        CameraLayout(layout_id="duplicate", cameras=(camera, camera))


def test_observation_point_layout_assigns_all_cameras() -> None:
    camera = CameraSpec(
        camera_id="point-001-cam-01",
        position=Position3D(x_m=1.0, y_m=2.0, z_m=5.0),
        orientation=CameraOrientation(yaw_rad=0.0, pitch_rad=0.0, roll_rad=0.0),
        horizontal_fov_rad=1.0,
        vertical_fov_rad=0.8,
        max_observation_distance_m=42.0,
        observation_interval_s=1.0,
    )
    camera_layout = CameraLayout(layout_id="resolved", cameras=(camera,))
    layout = ObservationPointLayout(
        layout_id="points",
        points=(
            ObservationPointSpec(
                point_id="point-001",
                position=camera.position,
                camera_ids=(camera.camera_id,),
            ),
        ),
        camera_layout=camera_layout,
        metadata={"placement_method": "test"},
    )

    assert layout.points[0].camera_ids == (camera.camera_id,)


def test_observation_point_layout_rejects_unassigned_camera() -> None:
    camera = CameraSpec(
        camera_id="camera-01",
        position=Position3D(x_m=1.0, y_m=2.0, z_m=5.0),
        orientation=CameraOrientation(yaw_rad=0.0, pitch_rad=0.0, roll_rad=0.0),
        horizontal_fov_rad=1.0,
        vertical_fov_rad=0.8,
        max_observation_distance_m=42.0,
        observation_interval_s=1.0,
    )
    with pytest.raises(ValidationError, match="assign every"):
        ObservationPointLayout(
            layout_id="invalid",
            points=(),
            camera_layout=CameraLayout(layout_id="resolved", cameras=(camera,)),
        )
