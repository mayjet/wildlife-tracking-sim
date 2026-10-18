from __future__ import annotations

from enum import Enum

from pydantic import Field, model_validator

from ._base import ContractModel
from .coordinates import Position2D, Velocity2D
from .distributions import PositionDistribution


class TrackStatus(str, Enum):
    OBSERVED = "OBSERVED"
    PREDICTED = "PREDICTED"
    EXIT_CANDIDATE = "EXIT_CANDIDATE"
    TERMINATED = "TERMINATED"


class TrackEstimate(ContractModel):
    track_id: str = Field(min_length=1)
    timestamp_s: float = Field(ge=0.0)
    position: Position2D
    velocity: Velocity2D | None = None
    status: TrackStatus
    position_distribution: PositionDistribution | None = None


class GroupTrackEstimate(ContractModel):
    group_track_id: str = Field(min_length=1)
    timestamp_s: float = Field(ge=0.0)
    center: Position2D
    estimated_member_count: int = Field(ge=0)
    observed_member_count: int = Field(ge=0)
    member_track_ids: tuple[str, ...] = ()
    status: TrackStatus
    center_distribution: PositionDistribution | None = None

    @model_validator(mode="after")
    def validate_member_counts(self) -> "GroupTrackEstimate":
        if self.observed_member_count > self.estimated_member_count:
            raise ValueError("observed_member_count cannot exceed estimated_member_count")
        if len(self.member_track_ids) > self.estimated_member_count:
            raise ValueError("member_track_ids cannot exceed estimated_member_count")
        if len(self.member_track_ids) != len(set(self.member_track_ids)):
            raise ValueError("member_track_ids must be unique")
        return self


class TrackingFrame(ContractModel):
    timestamp_s: float = Field(ge=0.0)
    tracks: tuple[TrackEstimate, ...] = ()
    groups: tuple[GroupTrackEstimate, ...] = ()

    @model_validator(mode="after")
    def validate_frame(self) -> "TrackingFrame":
        estimates = (*self.tracks, *self.groups)
        if any(estimate.timestamp_s != self.timestamp_s for estimate in estimates):
            raise ValueError("all tracking estimates must match the frame timestamp")
        track_ids = [track.track_id for track in self.tracks]
        group_ids = [group.group_track_id for group in self.groups]
        if len(track_ids) != len(set(track_ids)):
            raise ValueError("track_id values must be unique within a frame")
        if len(group_ids) != len(set(group_ids)):
            raise ValueError("group_track_id values must be unique within a frame")
        return self
