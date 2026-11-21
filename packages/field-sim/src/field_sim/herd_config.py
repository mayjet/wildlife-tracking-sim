from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class HerdProfile(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, allow_inf_nan=False)

    profile_id: str = Field(min_length=1)
    deer_count: int = Field(gt=0)
    adult_count: int = Field(ge=0)
    juvenile_count: int = Field(ge=0)
    formation: Literal["cluster"] = "cluster"
    group_radius_m: float = Field(default=10.0, gt=0.0)
    minimum_separation_m: float = Field(default=2.0, gt=0.0)
    follower_delay_s: float = Field(default=2.0, ge=0.0)
    speed_variation_mps: float = Field(default=0.15, ge=0.0)

    @model_validator(mode="after")
    def validate_counts_and_spacing(self) -> "HerdProfile":
        if self.adult_count + self.juvenile_count != self.deer_count:
            raise ValueError("adult_count + juvenile_count must equal deer_count")
        if self.deer_count > 1 and self.minimum_separation_m >= 2.0 * self.group_radius_m:
            raise ValueError("minimum_separation_m is too large for group_radius_m")
        return self


class HerdSimulationConfig(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, allow_inf_nan=False)

    case_id: str = Field(min_length=1)
    dataset_id: str = Field(min_length=1)
    route_id: str = Field(min_length=1)
    herd_id: str = Field(default="herd-001", min_length=1)
    seed: int = 0
    step_s: float = Field(default=1.0, gt=0.0)
    speed_mps: float = Field(default=1.5, gt=0.0)
    profile: HerdProfile
    local_avoidance_angles_deg: tuple[float, ...] = (
        -60.0,
        -45.0,
        -30.0,
        -15.0,
        15.0,
        30.0,
        45.0,
        60.0,
    )
    local_avoidance_radius_m: float = Field(default=6.0, gt=0.0)
    astar_lookahead_m: float = Field(default=20.0, gt=0.0)
