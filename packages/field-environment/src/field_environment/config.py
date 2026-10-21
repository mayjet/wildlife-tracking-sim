from __future__ import annotations

import hashlib
from enum import Enum
from pathlib import Path
from typing import Annotated, Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, model_validator
from shepherd_contracts import CameraOrientation

from .errors import EnvironmentConfigurationError
from .repository import resolve_repository_path


class CaseMode(str, Enum):
    CREATE = "create"
    LOAD = "load"
    EDIT = "edit"


class SyntheticTerrainConfig(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, allow_inf_nan=False)

    source: Literal["synthetic"]
    type: Literal["flat", "hills", "valley", "ridge"]
    size_m: float = Field(default=3000.0, gt=0.0)
    cell_size_m: float = Field(default=10.0, gt=0.0)
    relief_m: float = Field(default=120.0, ge=0.0)
    seed: int = 42
    parameters: dict[str, float | int] = Field(default_factory=dict)


class GeographicTerrainConfig(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, allow_inf_nan=False)

    source: Literal["alos", "gsi"]
    center_lat: float | None = Field(default=None, ge=-90.0, le=90.0)
    center_lon: float | None = Field(default=None, ge=-180.0, le=180.0)
    size_m: float = Field(default=3000.0, gt=0.0)
    cell_size_m: float = Field(default=10.0, gt=0.0)
    missing_data: Literal["error", "nearest"] = "nearest"
    offline: bool = False
    gsi_datasets: tuple[str, ...] = (
        "dem1a_png",
        "dem5a_png",
        "dem5b_png",
        "dem5c_png",
        "dem_png",
    )

    @model_validator(mode="after")
    def validate_center(self) -> "GeographicTerrainConfig":
        if self.center_lat is None or self.center_lon is None:
            raise ValueError("center_lat and center_lon are required for alos and gsi terrain")
        return self


class FileTerrainConfig(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, allow_inf_nan=False)

    source: Literal["file"]
    path: str = Field(min_length=1)
    cell_size_m: float | None = Field(default=None, gt=0.0)
    size_m: float | None = Field(default=None, gt=0.0)
    missing_data: Literal["error", "nearest"] = "nearest"


TerrainConfig = Annotated[
    SyntheticTerrainConfig | GeographicTerrainConfig | FileTerrainConfig,
    Field(discriminator="source"),
]


class FarmConfig(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, allow_inf_nan=False)

    boundary_type: Literal["rectangle", "file"] = "rectangle"
    size_m: float | None = Field(default=2000.0, gt=0.0)
    path: str | None = None

    @model_validator(mode="after")
    def validate_boundary(self) -> "FarmConfig":
        if self.boundary_type == "rectangle" and self.size_m is None:
            raise ValueError("farm.size_m is required for rectangle boundaries")
        if self.boundary_type == "file" and not self.path:
            raise ValueError("farm.path is required for file boundaries")
        return self


class FeatureInputConfig(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    status: Literal["unavailable", "empty", "available"] = "unavailable"
    path: str | None = None
    source: str | None = None
    assumed_height_m: float | None = Field(default=None, gt=0.0)

    @model_validator(mode="after")
    def validate_path(self) -> "FeatureInputConfig":
        if self.status == "available" and not self.path:
            raise ValueError("path is required when feature status is available")
        if self.status != "available" and self.path is not None:
            raise ValueError("path is only valid when feature status is available")
        return self


class EnvironmentFeaturesConfig(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    buildings: FeatureInputConfig = Field(default_factory=FeatureInputConfig)
    forest: FeatureInputConfig = Field(default_factory=FeatureInputConfig)
    difficult_slope_deg: float | None = Field(default=None, gt=0.0, lt=90.0)


class FixedCameraConfig(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, allow_inf_nan=False)

    camera_id: str = Field(min_length=1)
    x_m: float
    y_m: float
    height_above_ground_m: float = Field(gt=0.0)
    yaw_deg: float
    pitch_deg: float = 0.0
    roll_deg: float = 0.0
    horizontal_fov_deg: float = Field(default=80.0, gt=0.0, le=360.0)
    vertical_fov_deg: float = Field(default=50.0, gt=0.0, le=180.0)
    max_observation_distance_m: float = Field(default=42.0, gt=0.0)
    observation_interval_s: float = Field(default=1.0, gt=0.0)

    def orientation(self) -> CameraOrientation:
        from math import radians

        return CameraOrientation(
            yaw_rad=radians(self.yaw_deg),
            pitch_rad=radians(self.pitch_deg),
            roll_rad=radians(self.roll_deg),
        )


class EnvironmentConfig(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    case_id: str = Field(min_length=1)
    mode: CaseMode = CaseMode.CREATE
    source_case_id: str | None = None
    terrain: TerrainConfig | None = None
    farm: FarmConfig | None = None
    features: EnvironmentFeaturesConfig | None = None
    cameras: tuple[FixedCameraConfig, ...] = ()

    @model_validator(mode="after")
    def validate_mode(self) -> "EnvironmentConfig":
        if self.mode is CaseMode.CREATE and (self.terrain is None or self.farm is None):
            raise ValueError("create mode requires terrain and farm settings")
        if self.mode is CaseMode.LOAD and any(
            value is not None
            for value in (self.terrain, self.farm, self.features, self.source_case_id)
        ):
            raise ValueError("load mode accepts only case_id and display settings")
        if self.mode is CaseMode.LOAD and self.cameras:
            raise ValueError("load mode does not modify camera settings")
        if self.mode is CaseMode.EDIT and self.terrain is not None:
            raise ValueError("edit mode does not regenerate terrain; omit terrain settings")
        if self.source_case_id == self.case_id:
            raise ValueError("source_case_id must differ from case_id when cloning a Case")
        return self


def load_environment_config(
    path: str | Path,
    *,
    start: str | Path | None = None,
) -> tuple[EnvironmentConfig, Path]:
    resolved_path = resolve_repository_path(path, start=start)
    if not resolved_path.is_file():
        raise EnvironmentConfigurationError(f"configuration file not found: {resolved_path}")
    try:
        raw = yaml.safe_load(resolved_path.read_text(encoding="utf-8"))
        config = EnvironmentConfig.model_validate(raw)
    except Exception as error:
        raise EnvironmentConfigurationError(
            f"invalid environment configuration {resolved_path}: {error}"
        ) from error
    return config, resolved_path


def config_digest(config: EnvironmentConfig) -> str:
    payload = config.model_dump_json(exclude_none=True)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()
