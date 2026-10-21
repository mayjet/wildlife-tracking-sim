from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from numpy.typing import NDArray
from pydantic import BaseModel, ConfigDict, Field, model_validator
from shepherd_contracts import AxisAlignedBounds2D, Position2D


class TerrainGridSpec(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, allow_inf_nan=False)

    width_cells: int = Field(gt=0)
    height_cells: int = Field(gt=0)
    cell_size_m: float = Field(gt=0.0)
    origin: Position2D

    @classmethod
    def from_extent(
        cls,
        width_m: float,
        height_m: float,
        cell_size_m: float,
        *,
        min_x_m: float = 0.0,
        min_y_m: float = 0.0,
    ) -> "TerrainGridSpec":
        if width_m <= 0.0 or height_m <= 0.0 or cell_size_m <= 0.0:
            raise ValueError("terrain extent and cell size must be positive")
        width_cells = round(width_m / cell_size_m)
        height_cells = round(height_m / cell_size_m)
        if not np.isclose(width_cells * cell_size_m, width_m):
            raise ValueError("width_m must be an integer multiple of cell_size_m")
        if not np.isclose(height_cells * cell_size_m, height_m):
            raise ValueError("height_m must be an integer multiple of cell_size_m")
        return cls(
            width_cells=width_cells,
            height_cells=height_cells,
            cell_size_m=cell_size_m,
            origin=Position2D(
                x_m=min_x_m + cell_size_m / 2.0,
                y_m=min_y_m + cell_size_m / 2.0,
            ),
        )

    @property
    def bounds(self) -> AxisAlignedBounds2D:
        half_cell = self.cell_size_m / 2.0
        return AxisAlignedBounds2D(
            min_x_m=self.origin.x_m - half_cell,
            min_y_m=self.origin.y_m - half_cell,
            max_x_m=self.origin.x_m - half_cell + self.width_cells * self.cell_size_m,
            max_y_m=self.origin.y_m - half_cell + self.height_cells * self.cell_size_m,
        )

    @model_validator(mode="after")
    def validate_grid_size(self) -> "TerrainGridSpec":
        if self.width_cells * self.height_cells > 100_000_000:
            raise ValueError("terrain grid exceeds the 100 million cell safety limit")
        return self


@dataclass(frozen=True)
class Heightmap:
    values: NDArray[np.floating]
    grid: TerrainGridSpec

    def __post_init__(self) -> None:
        values = np.asarray(self.values)
        expected_shape = (self.grid.height_cells, self.grid.width_cells)
        if values.shape != expected_shape:
            raise ValueError(f"heightmap shape must be {expected_shape}, got {values.shape}")
        if values.dtype not in (np.dtype("float32"), np.dtype("float64")):
            raise TypeError("heightmap values must use float32 or float64")
        if not np.isfinite(values).all():
            raise ValueError("heightmap values must be finite")
        stored_values = np.array(values, copy=True, order="C")
        stored_values.setflags(write=False)
        object.__setattr__(self, "values", stored_values)

    @property
    def bounds(self) -> AxisAlignedBounds2D:
        return self.grid.bounds

    @property
    def width_m(self) -> float:
        return self.grid.width_cells * self.grid.cell_size_m

    @property
    def height_m(self) -> float:
        return self.grid.height_cells * self.grid.cell_size_m

    def cell_center(self, x_index: int, y_index: int) -> Position2D:
        if not 0 <= x_index < self.grid.width_cells:
            raise IndexError("x_index is outside the heightmap")
        if not 0 <= y_index < self.grid.height_cells:
            raise IndexError("y_index is outside the heightmap")
        return Position2D(
            x_m=self.grid.origin.x_m + x_index * self.grid.cell_size_m,
            y_m=self.grid.origin.y_m + y_index * self.grid.cell_size_m,
        )

    def indices_at(self, x_m: float, y_m: float) -> tuple[int, int]:
        bounds = self.bounds
        if not (bounds.min_x_m <= x_m < bounds.max_x_m):
            raise IndexError("x coordinate is outside the heightmap")
        if not (bounds.min_y_m <= y_m < bounds.max_y_m):
            raise IndexError("y coordinate is outside the heightmap")
        x_index = int(np.floor((x_m - bounds.min_x_m) / self.grid.cell_size_m))
        y_index = int(np.floor((y_m - bounds.min_y_m) / self.grid.cell_size_m))
        return x_index, y_index

    def elevation_at(self, x_m: float, y_m: float) -> float:
        x_index, y_index = self.indices_at(x_m, y_m)
        return float(self.values[y_index, x_index])

