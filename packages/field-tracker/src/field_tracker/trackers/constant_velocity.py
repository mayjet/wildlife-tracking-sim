from __future__ import annotations

from collections.abc import Mapping, Sequence

import numpy as np
from shapely.geometry import Point, Polygon
from shepherd_contracts import (
    JsonValue,
    Observation,
    Position2D,
    TrackEstimate,
    TrackingFrame,
    TrackStatus,
    Velocity2D,
)

from ..association import associate_measurements
from ..config import TrackerConfig
from ..filter import initial_state, predict_constant_velocity, update_position
from ..group_inference import GroupInferer
from ..lifecycle import (
    AssociationEvent,
    InternalTrackSnapshot,
    LifecycleEvent,
    TrackRecord,
    TrackerLifecycleState,
)
from ..measurement_fusion import FusedMeasurement, fuse_observations


class ConstantVelocityTracker:
    def __init__(self, *, preserve_velocity: bool = True):
        self.preserve_velocity = preserve_velocity
        self.config = TrackerConfig()
        self.records: dict[str, TrackRecord] = {}
        self.lifecycle_events: list[LifecycleEvent] = []
        self.association_events: list[AssociationEvent] = []
        self.internal_snapshots: list[InternalTrackSnapshot] = []
        self._next_track_number = 1
        self._last_timestamp_s: float | None = None
        self._group_inferer = GroupInferer(self.config)
        self._farm_boundary: Polygon | None = None

    @property
    def group_events(self):
        return tuple(self._group_inferer.events)

    def reset(self, config: Mapping[str, JsonValue], seed: int) -> None:
        self.config = TrackerConfig.model_validate(dict(config))
        self.records.clear()
        self.lifecycle_events.clear()
        self.association_events.clear()
        self.internal_snapshots.clear()
        self._next_track_number = 1
        self._last_timestamp_s = None
        self._group_inferer = GroupInferer(self.config)
        self._farm_boundary = (
            None
            if self.config.farm_boundary is None
            else Polygon(self.config.farm_boundary)
        )
        if self._farm_boundary is not None and not self._farm_boundary.is_valid:
            raise ValueError("farm_boundary must define a valid polygon")

    def _transition(
        self,
        record: TrackRecord,
        state: TrackerLifecycleState,
        timestamp_s: float,
        reason: str,
    ) -> None:
        if record.lifecycle_state is state:
            return
        previous = record.lifecycle_state
        record.lifecycle_state = state
        if state is TrackerLifecycleState.RETIRED:
            record.retired_at_s = timestamp_s
        self.lifecycle_events.append(
            LifecycleEvent(timestamp_s, record.track_id, previous, state, reason)
        )

    def _new_track(self, measurement: FusedMeasurement) -> TrackRecord:
        track_id = f"track-{self._next_track_number:06d}"
        self._next_track_number += 1
        state, covariance = initial_state(
            measurement.position, self.config.measurement_variance
        )
        record = TrackRecord(
            track_id=track_id,
            lifecycle_state=TrackerLifecycleState.TENTATIVE,
            state_vector=state,
            covariance=covariance,
            first_timestamp_s=measurement.timestamp_s,
            last_timestamp_s=measurement.timestamp_s,
            last_observed_timestamp_s=measurement.timestamp_s,
            age_class=measurement.age_class,
            candidate_observation_ids=measurement.source_observation_ids,
        )
        self.records[track_id] = record
        self.lifecycle_events.append(
            LifecycleEvent(
                measurement.timestamp_s,
                track_id,
                None,
                TrackerLifecycleState.TENTATIVE,
                "new measurement",
            )
        )
        if self.config.confirmation_hits == 1:
            self._transition(
                record,
                TrackerLifecycleState.TRACKED,
                measurement.timestamp_s,
                "confirmation threshold reached",
            )
        return record

    def _predict(self, record: TrackRecord, timestamp_s: float) -> None:
        delta_s = timestamp_s - record.last_timestamp_s
        if delta_s < 0.0:
            raise ValueError("tracker timestamps must be monotonic")
        if delta_s > 0.0:
            record.state_vector, record.covariance = predict_constant_velocity(
                record.state_vector,
                record.covariance,
                delta_s,
                self.config.process_variance,
            )
            if not self.preserve_velocity:
                record.state_vector[2:] = 0.0
            record.last_timestamp_s = timestamp_s
            record.age_steps += 1

    def _update_exit_state(self, record: TrackRecord, timestamp_s: float) -> TrackStatus:
        if self._farm_boundary is None:
            return (
                TrackStatus.OBSERVED
                if np.isclose(record.last_observed_timestamp_s, timestamp_s)
                else TrackStatus.PREDICTED
            )
        outside = not self._farm_boundary.covers(Point(*record.position))
        if outside:
            if record.exit_candidate_since_s is None:
                record.exit_candidate_since_s = timestamp_s
            if timestamp_s - record.exit_candidate_since_s >= self.config.exit_confirmation_s:
                return TrackStatus.EXIT_CANDIDATE
        else:
            record.exit_candidate_since_s = None
        return (
            TrackStatus.OBSERVED
            if np.isclose(record.last_observed_timestamp_s, timestamp_s)
            else TrackStatus.PREDICTED
        )

    def _estimate(self, record: TrackRecord, timestamp_s: float) -> TrackEstimate:
        status = (
            TrackStatus.TERMINATED
            if record.lifecycle_state is TrackerLifecycleState.RETIRED
            else self._update_exit_state(record, timestamp_s)
        )
        return TrackEstimate(
            track_id=record.track_id,
            timestamp_s=timestamp_s,
            position=Position2D(x_m=float(record.position[0]), y_m=float(record.position[1])),
            velocity=Velocity2D(
                x_mps=float(record.velocity[0]), y_mps=float(record.velocity[1])
            ),
            status=status,
        )

    def step(
        self, timestamp_s: float, observations: Sequence[Observation]
    ) -> TrackingFrame:
        if self._last_timestamp_s is not None and timestamp_s <= self._last_timestamp_s:
            raise ValueError("tracker step timestamps must be strictly increasing")
        if any(observation.timestamp_s != timestamp_s for observation in observations):
            raise ValueError("all observations must match timestamp_s")
        self._last_timestamp_s = timestamp_s
        measurements = fuse_observations(
            tuple(observations), self.config.duplicate_observation_tolerance_m
        )
        active = tuple(
            record
            for record in self.records.values()
            if record.lifecycle_state is not TrackerLifecycleState.RETIRED
        )
        for record in active:
            self._predict(record, timestamp_s)
        association = associate_measurements(active, measurements, self.config)
        assigned_track_indices = set()
        retired_this_step: list[TrackRecord] = []
        for assignment in association.assignments:
            assigned_track_indices.add(assignment.track_index)
            record = active[assignment.track_index]
            measurement = measurements[assignment.measurement_index]
            alternative = (
                None
                if assignment.alternative_measurement_index is None
                else measurements[assignment.alternative_measurement_index]
            )
            confidence = 1.0 / (1.0 + assignment.cost)
            record.association_confidence = confidence
            record.candidate_observation_ids = tuple(
                dict.fromkeys(
                    measurement.source_observation_ids
                    + (() if alternative is None else alternative.source_observation_ids)
                )
            )
            if assignment.ambiguous:
                self._transition(
                    record,
                    TrackerLifecycleState.AMBIGUOUS,
                    timestamp_s,
                    "multiple measurements have similar costs",
                )
            else:
                previous_position = record.position.copy()
                record.state_vector, record.covariance = update_position(
                    record.state_vector,
                    record.covariance,
                    measurement.position,
                    self.config.measurement_variance,
                )
                delta_s = max(timestamp_s - record.last_observed_timestamp_s, 1.0e-9)
                measured_velocity = (measurement.position - previous_position) / delta_s
                if self.preserve_velocity:
                    alpha = self.config.velocity_smoothing
                    record.state_vector[2:] = (
                        alpha * record.state_vector[2:] + (1.0 - alpha) * measured_velocity
                    )
                else:
                    record.state_vector[2:] = 0.0
                record.last_observed_timestamp_s = timestamp_s
                record.hit_count += 1
                record.consecutive_hit_count += 1
                record.missed_count = 0
                if record.age_class.value == "UNKNOWN":
                    record.age_class = measurement.age_class
                if (
                    record.lifecycle_state is TrackerLifecycleState.TENTATIVE
                    and record.hit_count >= self.config.confirmation_hits
                    and record.age_steps <= self.config.confirmation_window
                ):
                    self._transition(
                        record,
                        TrackerLifecycleState.TRACKED,
                        timestamp_s,
                        "confirmation threshold reached",
                    )
                elif record.lifecycle_state in {
                    TrackerLifecycleState.LOST,
                    TrackerLifecycleState.AMBIGUOUS,
                }:
                    self._transition(
                        record,
                        TrackerLifecycleState.TRACKED,
                        timestamp_s,
                        "unambiguous re-observation",
                    )
            self.association_events.append(
                AssociationEvent(
                    timestamp_s=timestamp_s,
                    track_id=record.track_id,
                    measurement_id=measurement.measurement_id,
                    selected_cost=assignment.cost,
                    alternative_measurement_id=(
                        None if alternative is None else alternative.measurement_id
                    ),
                    alternative_cost=assignment.alternative_cost,
                    confidence=confidence,
                )
            )
        for track_index in association.unmatched_track_indices:
            record = active[track_index]
            record.missed_count += 1
            record.consecutive_hit_count = 0
            record.candidate_observation_ids = ()
            if record.lifecycle_state is TrackerLifecycleState.TENTATIVE:
                if record.age_steps >= self.config.confirmation_window:
                    self._transition(
                        record,
                        TrackerLifecycleState.RETIRED,
                        timestamp_s,
                        "tentative confirmation window expired",
                    )
                    retired_this_step.append(record)
            elif timestamp_s - record.last_observed_timestamp_s >= self.config.retire_after_s:
                self._transition(
                    record,
                    TrackerLifecycleState.RETIRED,
                    timestamp_s,
                    "observation timeout",
                )
                retired_this_step.append(record)
            elif record.missed_count >= self.config.lost_after_misses:
                self._transition(
                    record,
                    TrackerLifecycleState.LOST,
                    timestamp_s,
                    "observation missed",
                )
            self.association_events.append(
                AssociationEvent(timestamp_s, record.track_id, None, None)
            )
        for measurement_index in association.unmatched_measurement_indices:
            self._new_track(measurements[measurement_index])
        retired_track_ids = {record.track_id for record in retired_this_step}
        snapshots = []
        for record in self.records.values():
            if (
                record.lifecycle_state is TrackerLifecycleState.RETIRED
                and record.track_id not in retired_track_ids
            ):
                continue
            snapshots.append(
                InternalTrackSnapshot(
                    timestamp_s=timestamp_s,
                    track_id=record.track_id,
                    lifecycle_state=record.lifecycle_state,
                    association_confidence=record.association_confidence,
                    hit_count=record.hit_count,
                    missed_count=record.missed_count,
                    candidate_observation_ids=record.candidate_observation_ids,
                )
            )
        self.internal_snapshots.extend(snapshots)
        public_records = tuple(
            record
            for record in self.records.values()
            if record.lifecycle_state
            in {
                TrackerLifecycleState.TRACKED,
                TrackerLifecycleState.LOST,
                TrackerLifecycleState.AMBIGUOUS,
            }
            or record.track_id in retired_track_ids
        )
        groups = self._group_inferer.infer(timestamp_s, public_records)
        return TrackingFrame(
            timestamp_s=timestamp_s,
            tracks=tuple(self._estimate(record, timestamp_s) for record in public_records),
            groups=groups,
        )

    def finalize(self) -> TrackingFrame | None:
        if self._last_timestamp_s is None:
            return None
        timestamp_s = self._last_timestamp_s
        terminated = []
        for record in self.records.values():
            if record.lifecycle_state is TrackerLifecycleState.RETIRED:
                continue
            self._transition(
                record,
                TrackerLifecycleState.RETIRED,
                timestamp_s,
                "tracker finalized",
            )
            terminated.append(self._estimate(record, timestamp_s))
        if not terminated:
            return None
        return TrackingFrame(timestamp_s=timestamp_s, tracks=tuple(terminated), groups=())
