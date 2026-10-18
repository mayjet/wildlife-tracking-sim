from __future__ import annotations

from pydantic import Field, model_validator

from ._base import ContractModel
from .animals import AgeClass
from .coordinates import Position2D, Position3D, Velocity2D


class GroundTruthState(ContractModel):
    timestamp_s: float = Field(ge=0.0)
    truth_id: str = Field(min_length=1)
    group_truth_id: str | None = None
    is_group_leader: bool = False
    position: Position2D | Position3D
    velocity: Velocity2D | None = None
    age_class: AgeClass = AgeClass.UNKNOWN

    @model_validator(mode="after")
    def validate_leader_membership(self) -> "GroundTruthState":
        if self.is_group_leader and self.group_truth_id is None:
            raise ValueError("a group leader must have group_truth_id")
        return self


class GroundTruthFrame(ContractModel):
    timestamp_s: float = Field(ge=0.0)
    states: tuple[GroundTruthState, ...]

    @model_validator(mode="after")
    def validate_timestamps_and_ids(self) -> "GroundTruthFrame":
        if any(state.timestamp_s != self.timestamp_s for state in self.states):
            raise ValueError("all ground-truth states must match the frame timestamp")
        truth_ids = [state.truth_id for state in self.states]
        if len(truth_ids) != len(set(truth_ids)):
            raise ValueError("truth_id values must be unique within a frame")
        return self
