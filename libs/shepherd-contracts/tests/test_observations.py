from __future__ import annotations

import pytest
from pydantic import ValidationError

from shepherd_contracts import AgeClass, Observation, ObservationFrame, Position2D


def test_observation_accepts_visible_attributes() -> None:
    observation = Observation(
        timestamp_s=2.0,
        camera_id="cam-1",
        observation_id="obs-1",
        position=Position2D(x_m=10.0, y_m=12.0),
        age_class=AgeClass.UNKNOWN,
    )
    assert observation.age_class is AgeClass.UNKNOWN


@pytest.mark.parametrize(
    "forbidden_field",
    ["truth_id", "group_truth_id", "is_group_leader", "future_position"],
)
def test_observation_rejects_ground_truth_fields(forbidden_field: str) -> None:
    payload = {
        "timestamp_s": 2.0,
        "camera_id": "cam-1",
        "observation_id": "obs-1",
        "position": {"x_m": 10.0, "y_m": 12.0},
        forbidden_field: "forbidden",
    }
    with pytest.raises(ValidationError):
        Observation.model_validate(payload)


def test_empty_observation_frame_is_valid() -> None:
    frame = ObservationFrame(timestamp_s=3.0)
    assert frame.observations == ()


def test_observation_frame_rejects_mismatched_timestamp() -> None:
    observation = Observation(
        timestamp_s=2.0,
        camera_id="cam-1",
        observation_id="obs-1",
        position=Position2D(x_m=10.0, y_m=12.0),
    )
    with pytest.raises(ValidationError):
        ObservationFrame(timestamp_s=3.0, observations=(observation,))


def test_missing_required_observation_field_is_rejected() -> None:
    with pytest.raises(ValidationError):
        Observation.model_validate(
            {
                "timestamp_s": 2.0,
                "camera_id": "cam-1",
                "position": {"x_m": 1.0, "y_m": 2.0},
            }
        )

