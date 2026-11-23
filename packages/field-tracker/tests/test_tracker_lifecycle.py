from __future__ import annotations

from shepherd_contracts import Observation, ObservationFrame, Position2D, TrackStatus

from field_tracker import (
    ConstantVelocityTracker,
    LastObservationTracker,
    TrackerLifecycleState,
    create_tracker,
    fuse_observations,
    run_tracker,
    run_tracker_stream,
)


def _observation(timestamp_s: float, observation_id: str, x_m: float, y_m: float):
    return Observation(
        timestamp_s=timestamp_s,
        camera_id=f"camera-{observation_id}",
        observation_id=observation_id,
        position=Position2D(x_m=x_m, y_m=y_m),
    )


def test_duplicate_camera_observations_are_fused_without_truth_fields() -> None:
    measurements = fuse_observations(
        (
            _observation(0.0, "first", 1.0, 2.0),
            _observation(0.0, "second", 1.0, 2.0),
        ),
        tolerance_m=0.01,
    )
    assert len(measurements) == 1
    assert measurements[0].source_observation_ids == ("first", "second")


def test_tentative_tracked_lost_reobserved_and_retired_transitions() -> None:
    frames = (
        ObservationFrame(timestamp_s=0.0, observations=(_observation(0.0, "a", 0.0, 0.0),)),
        ObservationFrame(timestamp_s=1.0, observations=(_observation(1.0, "b", 1.0, 0.0),)),
        ObservationFrame(timestamp_s=2.0, observations=(_observation(2.0, "c", 2.0, 0.0),)),
        ObservationFrame(timestamp_s=3.0, observations=()),
        ObservationFrame(timestamp_s=4.0, observations=(_observation(4.0, "d", 4.0, 0.0),)),
        ObservationFrame(timestamp_s=10.0, observations=()),
    )
    result = run_tracker(
        ConstantVelocityTracker(),
        frames,
        {
            "tracker_id": "cv-test",
            "confirmation_hits": 3,
            "confirmation_window": 5,
            "association_gate_m": 5.0,
            "lost_after_misses": 1,
            "retire_after_s": 5.0,
        },
        seed=42,
    )
    states = [event.current_state for event in result.lifecycle_events]
    assert TrackerLifecycleState.TENTATIVE in states
    assert TrackerLifecycleState.TRACKED in states
    assert TrackerLifecycleState.LOST in states
    assert TrackerLifecycleState.RETIRED in states
    assert result.frames[0].tracks == ()
    assert result.frames[2].tracks[0].status is TrackStatus.OBSERVED
    assert result.frames[3].tracks[0].status is TrackStatus.PREDICTED


def test_competing_measurements_mark_track_ambiguous() -> None:
    frames = (
        ObservationFrame(timestamp_s=0.0, observations=(_observation(0.0, "a", 0.0, 0.0),)),
        ObservationFrame(
            timestamp_s=1.0,
            observations=(
                _observation(1.0, "b", 1.0, 0.0),
                _observation(1.0, "c", -1.0, 0.0),
            ),
        ),
    )
    result = run_tracker(
        ConstantVelocityTracker(),
        frames,
        {
            "tracker_id": "ambiguous-test",
            "confirmation_hits": 1,
            "confirmation_window": 1,
            "association_gate_m": 5.0,
            "ambiguity_margin_m": 0.1,
        },
        seed=1,
    )
    assert any(
        event.current_state is TrackerLifecycleState.AMBIGUOUS
        for event in result.lifecycle_events
    )


def test_runner_signature_accepts_observation_frames_not_ground_truth() -> None:
    result = run_tracker(
        ConstantVelocityTracker(),
        (ObservationFrame(timestamp_s=0.0, observations=()),),
        {"tracker_id": "empty"},
        seed=0,
    )
    assert result.frames[0].tracks == ()


def test_stream_runner_notifies_each_observation_frame() -> None:
    frames = (
        ObservationFrame(timestamp_s=0.0, observations=()),
        ObservationFrame(timestamp_s=1.0, observations=()),
    )
    notifications = []
    result = run_tracker_stream(
        LastObservationTracker(),
        frames,
        {"tracker_id": "stream-test"},
        seed=0,
        on_frame=lambda observation, tracking: notifications.append(
            (observation.timestamp_s, tracking.timestamp_s)
        ),
    )
    assert notifications == [(0.0, 0.0), (1.0, 1.0)]
    assert len(result.frames) == 2


def test_exit_candidate_uses_estimated_track_position() -> None:
    frames = (
        ObservationFrame(
            timestamp_s=0.0,
            observations=(_observation(0.0, "outside-0", 20.0, 0.0),),
        ),
        ObservationFrame(
            timestamp_s=1.0,
            observations=(_observation(1.0, "outside-1", 21.0, 0.0),),
        ),
    )
    result = run_tracker(
        ConstantVelocityTracker(),
        frames,
        {
            "tracker_id": "exit-test",
            "confirmation_hits": 1,
            "confirmation_window": 1,
            "exit_confirmation_s": 1.0,
            "farm_boundary": (
                (-10.0, -10.0),
                (10.0, -10.0),
                (10.0, 10.0),
                (-10.0, 10.0),
                (-10.0, -10.0),
            ),
        },
        seed=0,
    )
    assert result.frames[1].tracks[0].status is TrackStatus.EXIT_CANDIDATE


def test_workspace_tracker_factory_is_loadable() -> None:
    tracker = create_tracker("custom_tracker")

    assert isinstance(tracker, LastObservationTracker)
