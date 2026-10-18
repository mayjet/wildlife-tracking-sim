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
