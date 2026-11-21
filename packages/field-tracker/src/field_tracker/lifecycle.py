from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum

import numpy as np
from shepherd_contracts import AgeClass


class TrackerLifecycleState(str, Enum):
    TENTATIVE = "TENTATIVE"
    TRACKED = "TRACKED"
    LOST = "LOST"
    AMBIGUOUS = "AMBIGUOUS"
    RETIRED = "RETIRED"


@dataclass
class TrackRecord:
    track_id: str
    lifecycle_state: TrackerLifecycleState
    state_vector: np.ndarray
    covariance: np.ndarray
    first_timestamp_s: float
    last_timestamp_s: float
    last_observed_timestamp_s: float
    age_class: AgeClass = AgeClass.UNKNOWN
    hit_count: int = 1
    consecutive_hit_count: int = 1
    age_steps: int = 1
    missed_count: int = 0
    association_confidence: float = 1.0
    candidate_observation_ids: tuple[str, ...] = ()
    exit_candidate_since_s: float | None = None
    retired_at_s: float | None = None

    @property
    def position(self) -> np.ndarray:
        return self.state_vector[:2]

    @property
    def velocity(self) -> np.ndarray:
        return self.state_vector[2:]


@dataclass(frozen=True)
class LifecycleEvent:
    timestamp_s: float
    track_id: str
    previous_state: TrackerLifecycleState | None
    current_state: TrackerLifecycleState
    reason: str


@dataclass(frozen=True)
class AssociationEvent:
    timestamp_s: float
    track_id: str
    measurement_id: str | None
    selected_cost: float | None
    alternative_measurement_id: str | None = None
    alternative_cost: float | None = None
    confidence: float = 0.0


@dataclass(frozen=True)
class InternalTrackSnapshot:
    timestamp_s: float
    track_id: str
    lifecycle_state: TrackerLifecycleState
    association_confidence: float
    hit_count: int
    missed_count: int
    candidate_observation_ids: tuple[str, ...] = field(default_factory=tuple)

