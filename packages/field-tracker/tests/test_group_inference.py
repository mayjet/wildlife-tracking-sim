from __future__ import annotations

import numpy as np
from shepherd_contracts import AgeClass

from field_tracker import GroupInferer, TrackRecord, TrackerConfig, TrackerLifecycleState


def _record(track_id: str, x_m: float) -> TrackRecord:
    return TrackRecord(
        track_id=track_id,
        lifecycle_state=TrackerLifecycleState.TRACKED,
        state_vector=np.asarray((x_m, 0.0, 1.0, 0.0)),
        covariance=np.eye(4),
        first_timestamp_s=0.0,
        last_timestamp_s=0.0,
        last_observed_timestamp_s=2.0,
        age_class=AgeClass.UNKNOWN,
    )


def test_group_requires_sustained_co_motion() -> None:
    inferer = GroupInferer(
        TrackerConfig(group_distance_m=10.0, group_confirmation_s=2.0)
    )
    records = (_record("track-a", 0.0), _record("track-b", 3.0))
    assert inferer.infer(0.0, records) == ()
    assert inferer.infer(1.0, records) == ()
    groups = inferer.infer(2.0, records)
    assert len(groups) == 1
    assert groups[0].estimated_member_count == 2


def test_group_id_survives_short_distance_violation() -> None:
    inferer = GroupInferer(
        TrackerConfig(
            group_distance_m=10.0,
            group_leave_distance_m=15.0,
            group_confirmation_s=1.0,
            group_leave_confirmation_s=2.0,
        )
    )
    close = (_record("track-a", 0.0), _record("track-b", 3.0))
    inferer.infer(0.0, close)
    initial = inferer.infer(1.0, close)
    separated = (_record("track-a", 0.0), _record("track-b", 20.0))
    transient = inferer.infer(2.0, separated)
    assert transient[0].group_track_id == initial[0].group_track_id
    assert inferer.infer(3.0, separated) == ()


def test_group_id_is_stable_when_membership_changes() -> None:
    inferer = GroupInferer(
        TrackerConfig(group_distance_m=10.0, group_confirmation_s=1.0)
    )
    pair = (_record("track-a", 0.0), _record("track-b", 3.0))
    inferer.infer(0.0, pair)
    first = inferer.infer(1.0, pair)
    triple = (*pair, _record("track-c", 5.0))
    second = inferer.infer(2.0, triple)
    assert first[0].group_track_id == second[0].group_track_id


def test_group_split_is_recorded_after_sustained_separation() -> None:
    inferer = GroupInferer(
        TrackerConfig(
            group_distance_m=10.0,
            group_leave_distance_m=15.0,
            group_confirmation_s=1.0,
            group_leave_confirmation_s=1.0,
        )
    )
    together = tuple(_record(f"track-{index}", float(index)) for index in range(4))
    inferer.infer(0.0, together)
    inferer.infer(1.0, together)
    separated = (
        _record("track-0", 0.0),
        _record("track-1", 1.0),
        _record("track-2", 20.0),
        _record("track-3", 21.0),
    )
    groups = inferer.infer(2.0, separated)
    assert len(groups) == 2
    assert any(event.event_type == "SPLIT" for event in inferer.events)
