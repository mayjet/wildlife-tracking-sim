from __future__ import annotations

from math import pi
from pathlib import PurePosixPath

from pydantic import Field, field_validator, model_validator

from ._base import ContractModel, JsonValue
from .coordinates import (
    AxisAlignedBounds2D,
    CameraOrientation,
    LocalCoordinateSystem,
    Position3D,
)

DEFAULT_MAX_OBSERVATION_DISTANCE_M = 42.0


def _validate_relative_reference(value: str) -> str:
    path = PurePosixPath(value)
    if not value or path.is_absolute() or ".." in path.parts:
        raise ValueError("data references must be non-empty paths relative to the case directory")
    return value


class EnvironmentDataRefs(ContractModel):
    terrain: str | None = None
    landcover: str | None = None
    traversability: str | None = None
    environment_usd: str | None = None
    source_directory: str | None = None

    @field_validator("terrain", "landcover", "traversability", "environment_usd", "source_directory")
    @classmethod
    def validate_references(cls, value: str | None) -> str | None:
        return None if value is None else _validate_relative_reference(value)


class FarmBoundarySpec(ContractModel):
    data_ref: str
    bounds: AxisAlignedBounds2D

    @field_validator("data_ref")
    @classmethod
    def validate_reference(cls, value: str) -> str:
        return _validate_relative_reference(value)


class CaseSpec(ContractModel):
    schema_version: str = Field(min_length=1)
    case_id: str = Field(min_length=1)
    coordinate_system: LocalCoordinateSystem
    environment: EnvironmentDataRefs
    farm_boundary: FarmBoundarySpec


class CameraSpec(ContractModel):
    camera_id: str = Field(min_length=1)
    position: Position3D
    orientation: CameraOrientation
    horizontal_fov_rad: float = Field(gt=0.0, le=2.0 * pi)
    vertical_fov_rad: float = Field(gt=0.0, le=pi)
    max_observation_distance_m: float = Field(gt=0.0)
    observation_interval_s: float = Field(gt=0.0)


class CameraLayout(ContractModel):
    layout_id: str = Field(min_length=1)
    cameras: tuple[CameraSpec, ...]

    @model_validator(mode="after")
    def validate_unique_camera_ids(self) -> "CameraLayout":
        camera_ids = [camera.camera_id for camera in self.cameras]
        if len(camera_ids) != len(set(camera_ids)):
            raise ValueError("camera_id values must be unique within a layout")
        return self


class ObservationPointSpec(ContractModel):
    point_id: str = Field(min_length=1)
    position: Position3D
    camera_ids: tuple[str, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def validate_unique_camera_ids(self) -> "ObservationPointSpec":
        if len(self.camera_ids) != len(set(self.camera_ids)):
            raise ValueError("camera_ids must be unique within an observation point")
        return self


class ObservationPointLayout(ContractModel):
    layout_id: str = Field(min_length=1)
    points: tuple[ObservationPointSpec, ...]
    camera_layout: CameraLayout
    metadata: dict[str, JsonValue] = Field(default_factory=dict)

    @model_validator(mode="after")
    def validate_layout_membership(self) -> "ObservationPointLayout":
        point_ids = [point.point_id for point in self.points]
        if len(point_ids) != len(set(point_ids)):
            raise ValueError("point_id values must be unique within a layout")
        assigned = [camera_id for point in self.points for camera_id in point.camera_ids]
        if len(assigned) != len(set(assigned)):
            raise ValueError("a camera cannot belong to multiple observation points")
        camera_ids = {camera.camera_id for camera in self.camera_layout.cameras}
        if set(assigned) != camera_ids:
            raise ValueError("observation points must assign every CameraLayout camera exactly once")
        return self
