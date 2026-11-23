from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass

from shepherd_contracts import JsonValue, ObservationFrame, Tracker, TrackingFrame

from .group_inference import GroupLifecycleEvent
from .lifecycle import AssociationEvent, InternalTrackSnapshot, LifecycleEvent


@dataclass(frozen=True)
class TrackingResult:
    tracker_id: str
    frames: tuple[TrackingFrame, ...]
    lifecycle_events: tuple[LifecycleEvent, ...]
    association_events: tuple[AssociationEvent, ...]
    internal_states: tuple[InternalTrackSnapshot, ...]
    group_events: tuple[GroupLifecycleEvent, ...] = ()


# Ground Truthを受け取らずObservationFrameだけでTrackerを実行する．
def run_tracker(
    tracker: Tracker,
    observation_frames: tuple[ObservationFrame, ...],
    config: Mapping[str, JsonValue],
    seed: int,
) -> TrackingResult:
    return run_tracker_stream(tracker, observation_frames, config, seed)


# Trackerの各時刻の結果を表示・記録処理へ逐次通知する．
def run_tracker_stream(
    tracker: Tracker,
    observation_frames: tuple[ObservationFrame, ...],
    config: Mapping[str, JsonValue],
    seed: int,
    *,
    on_frame: Callable[[ObservationFrame, TrackingFrame], None] | None = None,
) -> TrackingResult:
    tracker.reset(config, seed)
    frames = []
    for observation_frame in observation_frames:
        tracking_frame = tracker.step(
            observation_frame.timestamp_s, observation_frame.observations
        )
        frames.append(tracking_frame)
        if on_frame is not None:
            on_frame(observation_frame, tracking_frame)
    tracker.finalize()
    return TrackingResult(
        tracker_id=str(
            getattr(getattr(tracker, "config", None), "tracker_id", None)
            or config.get("tracker_id", type(tracker).__name__)
        ),
        frames=tuple(frames),
        lifecycle_events=tuple(getattr(tracker, "lifecycle_events", ())),
        association_events=tuple(getattr(tracker, "association_events", ())),
        internal_states=tuple(getattr(tracker, "internal_snapshots", ())),
        group_events=tuple(getattr(tracker, "group_events", ())),
    )
