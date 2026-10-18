from __future__ import annotations

from enum import Enum
from typing import Annotated, Literal, TypeAlias

from pydantic import Field, model_validator

from ._base import ContractModel
from .coordinates import Position2D


class GaussianPositionDistribution(ContractModel):
    kind: Literal["gaussian"] = "gaussian"
    mean: Position2D
    covariance_m2: tuple[tuple[float, float], tuple[float, float]]

    @model_validator(mode="after")
    def validate_covariance(self) -> "GaussianPositionDistribution":
        xx, xy = self.covariance_m2[0]
        yx, yy = self.covariance_m2[1]
        if abs(xy - yx) > 1e-9:
            raise ValueError("covariance_m2 must be symmetric in x,y order")
        if xx < 0.0 or yy < 0.0 or xx * yy - xy * yx < -1e-9:
            raise ValueError("covariance_m2 must be positive semidefinite")
        return self


class Particle2D(ContractModel):
    position: Position2D
    weight: float = Field(ge=0.0)


class ParticlePositionDistribution(ContractModel):
    kind: Literal["particles"] = "particles"
    particles: tuple[Particle2D, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def validate_weights(self) -> "ParticlePositionDistribution":
        total_weight = sum(particle.weight for particle in self.particles)
        if abs(total_weight - 1.0) > 1e-6:
            raise ValueError("particle weights must sum to 1")
        return self


class GridAxisOrder(str, Enum):
    YX = "YX"


class GridAxisDirection(str, Enum):
    INCREASING = "INCREASING"
    DECREASING = "DECREASING"


class GridValueSemantics(str, Enum):
    PROBABILITY_MASS = "PROBABILITY_MASS"
    PROBABILITY_DENSITY_PER_M2 = "PROBABILITY_DENSITY_PER_M2"


class GridPositionDistribution(ContractModel):
    kind: Literal["grid"] = "grid"
    cell_size_m: float = Field(gt=0.0)
    origin: Position2D
    origin_is_cell_center: Literal[True] = True
    axis_order: GridAxisOrder = GridAxisOrder.YX
    x_direction: GridAxisDirection = GridAxisDirection.INCREASING
    y_direction: GridAxisDirection = GridAxisDirection.INCREASING
    value_semantics: GridValueSemantics
    values: tuple[tuple[float, ...], ...] = Field(min_length=1)

    @model_validator(mode="after")
    def validate_values(self) -> "GridPositionDistribution":
        row_lengths = {len(row) for row in self.values}
        if row_lengths == {0} or len(row_lengths) != 1:
            raise ValueError("grid values must be a non-empty rectangular array")
        flattened = [value for row in self.values for value in row]
        if any(value < 0.0 for value in flattened):
            raise ValueError("grid probability values must be non-negative")
        if self.value_semantics is GridValueSemantics.PROBABILITY_MASS:
            if abs(sum(flattened) - 1.0) > 1e-6:
                raise ValueError("probability-mass grid values must sum to 1")
        elif sum(flattened) <= 0.0:
            raise ValueError("probability-density grid must contain positive density")
        return self


PositionDistribution: TypeAlias = Annotated[
    GaussianPositionDistribution | ParticlePositionDistribution | GridPositionDistribution,
    Field(discriminator="kind"),
]
