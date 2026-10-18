from __future__ import annotations

from enum import Enum
from math import pi

from pydantic import Field, model_validator

from ._base import ContractModel


class HorizontalAxisDirection(str, Enum):
    EAST = "EAST"
    NORTH = "NORTH"
    WEST = "WEST"
    SOUTH = "SOUTH"


class VerticalAxisDirection(str, Enum):
    UP = "UP"


class Position2D(ContractModel):
    x_m: float
    y_m: float


class Position3D(Position2D):
    z_m: float


class Velocity2D(ContractModel):
    x_mps: float
    y_mps: float


class GeodeticOrigin(ContractModel):
    latitude_deg: float = Field(ge=-90.0, le=90.0)
    longitude_deg: float = Field(ge=-180.0, le=180.0)
    altitude_m: float = 0.0


class LocalCoordinateSystem(ContractModel):
    name: str = Field(min_length=1)
    x_axis: HorizontalAxisDirection = HorizontalAxisDirection.EAST
    y_axis: HorizontalAxisDirection = HorizontalAxisDirection.NORTH
    z_axis: VerticalAxisDirection = VerticalAxisDirection.UP
    origin_description: str = Field(min_length=1)
    geodetic_origin: GeodeticOrigin | None = None
    geographic_crs: str | None = None
    projected_crs: str | None = None
    geographic_conversion: str | None = None
    vertical_datum: str = Field(min_length=1)

    @model_validator(mode="after")
    def validate_horizontal_axes(self) -> "LocalCoordinateSystem":
        east_west = {HorizontalAxisDirection.EAST, HorizontalAxisDirection.WEST}
        north_south = {HorizontalAxisDirection.NORTH, HorizontalAxisDirection.SOUTH}
        if not (
            (self.x_axis in east_west and self.y_axis in north_south)
            or (self.x_axis in north_south and self.y_axis in east_west)
        ):
            raise ValueError("x_axis and y_axis must describe perpendicular horizontal axes")
        if self.geodetic_origin is not None and self.geographic_conversion is None:
            raise ValueError("geographic_conversion is required with geodetic_origin")
        return self


class CameraOrientation(ContractModel):
    yaw_rad: float = Field(ge=-pi, le=pi)
    pitch_rad: float = Field(ge=-pi / 2.0, le=pi / 2.0)
    roll_rad: float = Field(ge=-pi, le=pi)


class AxisAlignedBounds2D(ContractModel):
    min_x_m: float
    min_y_m: float
    max_x_m: float
    max_y_m: float

    @model_validator(mode="after")
    def validate_bounds(self) -> "AxisAlignedBounds2D":
        if self.max_x_m <= self.min_x_m or self.max_y_m <= self.min_y_m:
            raise ValueError("maximum bounds must be greater than minimum bounds")
        return self
