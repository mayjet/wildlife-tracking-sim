from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field, model_validator


class TrackerConfig(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, allow_inf_nan=False)

    tracker_id: str = Field(default="constant-velocity", min_length=1)
    confirmation_hits: int = Field(default=3, gt=0)
    confirmation_window: int = Field(default=5, gt=0)
    association_gate_m: float = Field(default=8.0, gt=0.0)
    ambiguity_margin_m: float = Field(default=1.5, ge=0.0)
    duplicate_observation_tolerance_m: float = Field(default=0.05, ge=0.0)
    lost_after_misses: int = Field(default=1, gt=0)
    retire_after_s: float = Field(default=15.0, gt=0.0)
    exit_confirmation_s: float = Field(default=5.0, ge=0.0)
    velocity_smoothing: float = Field(default=0.5, ge=0.0, le=1.0)
    process_variance: float = Field(default=1.0, gt=0.0)
    measurement_variance: float = Field(default=0.01, gt=0.0)
    direction_cost_weight: float = Field(default=1.0, ge=0.0)
    age_mismatch_cost: float = Field(default=2.0, ge=0.0)
    group_distance_m: float = Field(default=20.0, gt=0.0)
    group_leave_distance_m: float | None = Field(default=None, gt=0.0)
    group_velocity_difference_mps: float = Field(default=1.0, ge=0.0)
    group_confirmation_s: float = Field(default=3.0, ge=0.0)
    group_leave_confirmation_s: float = Field(default=3.0, ge=0.0)
    farm_boundary: tuple[tuple[float, float], ...] | None = None

    @model_validator(mode="after")
    def validate_windows(self) -> "TrackerConfig":
        if self.confirmation_hits > self.confirmation_window:
            raise ValueError("confirmation_hits cannot exceed confirmation_window")
        if self.farm_boundary is not None and len(self.farm_boundary) < 3:
            raise ValueError("farm_boundary requires at least three coordinates")
        if (
            self.group_leave_distance_m is not None
            and self.group_leave_distance_m < self.group_distance_m
        ):
            raise ValueError("group_leave_distance_m cannot be smaller than group_distance_m")
        return self

    @property
    def resolved_group_leave_distance_m(self) -> float:
        return (
            self.group_distance_m * 1.25
            if self.group_leave_distance_m is None
            else self.group_leave_distance_m
        )
