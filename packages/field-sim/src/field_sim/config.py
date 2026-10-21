from __future__ import annotations

from pathlib import Path
from typing import Annotated, Literal

import numpy as np
import yaml
from pydantic import BaseModel, ConfigDict, Field, model_validator
from shepherd_contracts import AgeClass, Position2D, Velocity2D

from field_environment import resolve_repository_path


class StationaryMotion(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    kind: Literal["stationary"]
    position: Position2D


class LinearMotion(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    kind: Literal["linear"]
    start: Position2D
    velocity: Velocity2D


class TimedWaypoint(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, allow_inf_nan=False)

    timestamp_s: float = Field(ge=0.0)
    position: Position2D


class WaypointMotion(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    kind: Literal["waypoints"]
    waypoints: tuple[TimedWaypoint, ...] = Field(min_length=2)

    @model_validator(mode="after")
    def validate_waypoints(self) -> "WaypointMotion":
        timestamps = [waypoint.timestamp_s for waypoint in self.waypoints]
        if timestamps[0] != 0.0:
            raise ValueError("the first waypoint timestamp must be 0")
        if any(current <= previous for previous, current in zip(timestamps, timestamps[1:])):
            raise ValueError("waypoint timestamps must be strictly increasing")
        return self


MotionConfig = Annotated[
    StationaryMotion | LinearMotion | WaypointMotion,
    Field(discriminator="kind"),
]


class SimulationConfig(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, allow_inf_nan=False)

    case_id: str = Field(min_length=1)
    dataset_id: str = Field(min_length=1)
    seed: int = 0
    duration_s: float = Field(gt=0.0)
    step_s: float = Field(gt=0.0)
    truth_id: str = Field(default="deer-001", min_length=1)
    age_class: AgeClass = AgeClass.UNKNOWN
    motion: MotionConfig

    @model_validator(mode="after")
    def validate_duration(self) -> "SimulationConfig":
        steps = self.duration_s / self.step_s
        if not np.isclose(steps, round(steps), rtol=0.0, atol=1e-9):
            raise ValueError("duration_s must be an integer multiple of step_s")
        if isinstance(self.motion, WaypointMotion):
            if self.motion.waypoints[-1].timestamp_s < self.duration_s:
                raise ValueError("the final waypoint must cover the simulation duration")
        return self


def load_simulation_config(
    path: str | Path,
    *,
    start: str | Path | None = None,
) -> tuple[SimulationConfig, Path]:
    resolved_path = resolve_repository_path(path, start=start)
    if not resolved_path.is_file():
        raise FileNotFoundError(f"simulation configuration not found: {resolved_path}")
    raw = yaml.safe_load(resolved_path.read_text(encoding="utf-8"))
    return SimulationConfig.model_validate(raw), resolved_path
