from __future__ import annotations

from math import pi
from pathlib import Path

import yaml
from pydantic import BaseModel, ConfigDict, Field

from field_environment import resolve_repository_path

from ..observation_points import CameraMountProfile


class CameraMountDefinition(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, allow_inf_nan=False)

    pole_height_m: float = Field(default=5.0, gt=0.0)
    camera_count: int = Field(default=6, ge=1, le=64)
    horizontal_fov_deg: float = Field(default=60.0, gt=0.0, le=360.0)
    vertical_fov_deg: float = Field(default=48.0, gt=0.0, le=180.0)
    max_observation_distance_m: float = Field(default=42.0, gt=0.0)
    observation_interval_s: float = Field(default=1.0, gt=0.0)
    first_yaw_deg: float = Field(default=0.0, ge=-180.0, le=180.0)
    pitch_deg: float | None = Field(default=None, ge=-90.0, le=90.0)
    pitch_target_height_m: float = Field(default=0.75, ge=0.0)
    pitch_reference_distance_m: float = Field(default=20.0, gt=0.0)

    def to_profile(self, profile_id: str) -> CameraMountProfile:
        return CameraMountProfile(
            profile_id=profile_id,
            pole_height_m=self.pole_height_m,
            camera_count=self.camera_count,
            horizontal_fov_rad=self.horizontal_fov_deg * pi / 180.0,
            vertical_fov_rad=self.vertical_fov_deg * pi / 180.0,
            max_observation_distance_m=self.max_observation_distance_m,
            observation_interval_s=self.observation_interval_s,
            first_yaw_rad=self.first_yaw_deg * pi / 180.0,
            pitch_rad=None if self.pitch_deg is None else self.pitch_deg * pi / 180.0,
            pitch_target_height_m=self.pitch_target_height_m,
            pitch_reference_distance_m=self.pitch_reference_distance_m,
        )


class PlacementDefinition(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    layout_id: str = Field(min_length=1)
    method: str = Field(min_length=1)
    module: str | None = None
    seed: int = 0
    parent_layout_id: str | None = None
    mount: CameraMountDefinition = CameraMountDefinition()
    parameters: dict[str, object] = Field(default_factory=dict)


def load_placement_definition(
    path: str | Path,
    *,
    start: str | Path | None = None,
) -> tuple[PlacementDefinition, Path]:
    resolved = resolve_repository_path(path, start=start)
    if not resolved.is_file():
        raise FileNotFoundError(f"placement definition not found: {resolved}")
    raw = yaml.safe_load(resolved.read_text(encoding="utf-8"))
    return PlacementDefinition.model_validate(raw), resolved
