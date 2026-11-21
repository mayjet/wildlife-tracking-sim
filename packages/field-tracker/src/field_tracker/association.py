from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from scipy.optimize import linear_sum_assignment
from shepherd_contracts import AgeClass

from .config import TrackerConfig
from .lifecycle import TrackRecord
from .measurement_fusion import FusedMeasurement


@dataclass(frozen=True)
class TrackAssignment:
    track_index: int
    measurement_index: int
    cost: float
    alternative_measurement_index: int | None
    alternative_cost: float | None
    ambiguous: bool


@dataclass(frozen=True)
class AssociationResult:
    assignments: tuple[TrackAssignment, ...]
    unmatched_track_indices: tuple[int, ...]
    unmatched_measurement_indices: tuple[int, ...]


def _cost(
    track: TrackRecord,
    measurement: FusedMeasurement,
    config: TrackerConfig,
) -> float:
    delta = measurement.position - track.position
    distance = float(np.linalg.norm(delta))
    if distance > config.association_gate_m:
        return np.inf
    direction_cost = 0.0
    speed = float(np.linalg.norm(track.velocity))
    displacement = float(np.linalg.norm(delta))
    if speed > 1.0e-6 and displacement > 1.0e-6:
        cosine = float(np.clip(np.dot(track.velocity, delta) / (speed * displacement), -1.0, 1.0))
        direction_cost = config.direction_cost_weight * (1.0 - cosine)
    age_cost = 0.0
    if (
        track.age_class is not AgeClass.UNKNOWN
        and measurement.age_class is not AgeClass.UNKNOWN
        and track.age_class is not measurement.age_class
    ):
        age_cost = config.age_mismatch_cost
    return distance + direction_cost + age_cost


def associate_measurements(
    tracks: tuple[TrackRecord, ...],
    measurements: tuple[FusedMeasurement, ...],
    config: TrackerConfig,
) -> AssociationResult:
    if not tracks or not measurements:
        return AssociationResult(
            assignments=(),
            unmatched_track_indices=tuple(range(len(tracks))),
            unmatched_measurement_indices=tuple(range(len(measurements))),
        )
    costs = np.asarray(
        [[_cost(track, measurement, config) for measurement in measurements] for track in tracks]
    )
    finite = np.isfinite(costs)
    safe_costs = np.where(finite, costs, 1.0e12)
    row_indices, column_indices = linear_sum_assignment(safe_costs)
    assignments = []
    used_tracks = set()
    used_measurements = set()
    for track_index, measurement_index in zip(row_indices, column_indices):
        selected_cost = float(costs[track_index, measurement_index])
        if not np.isfinite(selected_cost):
            continue
        alternatives = [
            (float(costs[track_index, index]), index)
            for index in range(len(measurements))
            if index != measurement_index and np.isfinite(costs[track_index, index])
        ]
        alternatives.sort()
        alternative_cost, alternative_index = alternatives[0] if alternatives else (None, None)
        ambiguous = (
            alternative_cost is not None
            and alternative_cost - selected_cost <= config.ambiguity_margin_m
        )
        assignments.append(
            TrackAssignment(
                track_index=int(track_index),
                measurement_index=int(measurement_index),
                cost=selected_cost,
                alternative_measurement_index=alternative_index,
                alternative_cost=alternative_cost,
                ambiguous=ambiguous,
            )
        )
        used_tracks.add(int(track_index))
        used_measurements.add(int(measurement_index))
    return AssociationResult(
        assignments=tuple(assignments),
        unmatched_track_indices=tuple(set(range(len(tracks))) - used_tracks),
        unmatched_measurement_indices=tuple(set(range(len(measurements))) - used_measurements),
    )
