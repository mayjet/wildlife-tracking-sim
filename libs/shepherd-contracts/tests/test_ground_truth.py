from __future__ import annotations

import pytest
from pydantic import ValidationError

from shepherd_contracts import GroundTruthFrame, GroundTruthState, Position2D


def test_ground_truth_keeps_simulator_only_identifiers() -> None:
    state = GroundTruthState(
        timestamp_s=1.0,
        truth_id="deer-1",
        group_truth_id="herd-1",
        is_group_leader=True,
        position=Position2D(x_m=2.0, y_m=3.0),
    )
    frame = GroundTruthFrame(timestamp_s=1.0, states=(state,))
    assert frame.states[0].truth_id == "deer-1"


def test_ground_truth_frame_rejects_duplicate_truth_ids() -> None:
    state = GroundTruthState(
        timestamp_s=1.0,
        truth_id="deer-1",
        position=Position2D(x_m=2.0, y_m=3.0),
    )
    with pytest.raises(ValidationError):
        GroundTruthFrame(timestamp_s=1.0, states=(state, state))


def test_group_leader_requires_group_identifier() -> None:
    with pytest.raises(ValidationError):
        GroundTruthState(
            timestamp_s=1.0,
            truth_id="deer-1",
            is_group_leader=True,
            position=Position2D(x_m=2.0, y_m=3.0),
        )
