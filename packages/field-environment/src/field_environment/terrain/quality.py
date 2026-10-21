from __future__ import annotations

import numpy as np
from pydantic import BaseModel, ConfigDict, Field
from scipy import ndimage

from ..errors import TerrainMissingDataError
from .heightmap import Heightmap, TerrainGridSpec


class TerrainQuality(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, allow_inf_nan=False)

    minimum_elevation_m: float
    maximum_elevation_m: float
    relief_m: float = Field(ge=0.0)
    missing_fraction_before_fill: float = Field(ge=0.0, le=1.0)
    valid_cell_count: int = Field(ge=0)
    mean_slope_deg: float = Field(ge=0.0)
    maximum_slope_deg: float = Field(ge=0.0)
    output_cell_size_m: float = Field(gt=0.0)
    effective_source_resolution_m: float | None = Field(default=None, gt=0.0)
    fill_method: str


def fill_missing_elevations(values: np.ndarray, method: str) -> tuple[np.ndarray, float]:
    values = np.asarray(values, dtype=np.float64)
    missing = ~np.isfinite(values)
    missing_fraction = float(missing.mean())
    if not missing.any():
        return values, missing_fraction
    if missing.all():
        raise TerrainMissingDataError("elevation source contains no valid cells")
    if method == "error":
        raise TerrainMissingDataError(
            f"elevation source contains {missing_fraction:.2%} missing cells"
        )
    if method != "nearest":
        raise ValueError(f"unsupported missing-data method: {method}")
    nearest_indices = ndimage.distance_transform_edt(
        missing, return_distances=False, return_indices=True
    )
    return values[tuple(nearest_indices)], missing_fraction


def slope_degrees(values: np.ndarray, cell_size_m: float) -> np.ndarray:
    gradient_y, gradient_x = np.gradient(values, cell_size_m, cell_size_m)
    return np.degrees(np.arctan(np.hypot(gradient_x, gradient_y)))


def calculate_terrain_quality(
    values: np.ndarray,
    grid: TerrainGridSpec,
    *,
    missing_fraction_before_fill: float = 0.0,
    effective_source_resolution_m: float | None = None,
    fill_method: str = "none",
) -> TerrainQuality:
    finite_values = np.asarray(values)[np.isfinite(values)]
    if not len(finite_values):
        raise TerrainMissingDataError("terrain has no finite elevation values")
    slope = slope_degrees(np.asarray(values, dtype=float), grid.cell_size_m)
    minimum = float(finite_values.min())
    maximum = float(finite_values.max())
    return TerrainQuality(
        minimum_elevation_m=minimum,
        maximum_elevation_m=maximum,
        relief_m=maximum - minimum,
        missing_fraction_before_fill=missing_fraction_before_fill,
        valid_cell_count=int(len(finite_values)),
        mean_slope_deg=float(np.mean(slope)),
        maximum_slope_deg=float(np.max(slope)),
        output_cell_size_m=grid.cell_size_m,
        effective_source_resolution_m=effective_source_resolution_m,
        fill_method=fill_method,
    )


def heightmap_quality(heightmap: Heightmap) -> TerrainQuality:
    return calculate_terrain_quality(heightmap.values, heightmap.grid)
