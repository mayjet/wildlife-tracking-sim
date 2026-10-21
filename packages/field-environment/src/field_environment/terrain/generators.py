from __future__ import annotations

from enum import Enum
from math import cos, sin
from typing import Any

import numpy as np

from .heightmap import Heightmap, TerrainGridSpec


class TerrainKind(str, Enum):
    FLAT = "flat"
    HILLS = "hills"
    VALLEY = "valley"
    RIDGE = "ridge"


def _coordinate_mesh(grid: TerrainGridSpec) -> tuple[np.ndarray, np.ndarray]:
    x_values = grid.origin.x_m + np.arange(grid.width_cells) * grid.cell_size_m
    y_values = grid.origin.y_m + np.arange(grid.height_cells) * grid.cell_size_m
    return np.meshgrid(x_values, y_values)


def generate_flat(
    grid: TerrainGridSpec,
    *,
    elevation_m: float = 0.0,
    dtype: np.dtype[Any] | type[np.floating[Any]] = np.float32,
) -> Heightmap:
    values = np.full(
        (grid.height_cells, grid.width_cells), elevation_m, dtype=np.dtype(dtype)
    )
    return Heightmap(values=values, grid=grid)


def generate_hills(
    grid: TerrainGridSpec,
    *,
    seed: int,
    base_elevation_m: float = 0.0,
    hill_count: int = 6,
    hill_height_m: float = 30.0,
    hill_radius_m: float = 350.0,
    dtype: np.dtype[Any] | type[np.floating[Any]] = np.float32,
) -> Heightmap:
    if hill_count <= 0 or hill_height_m < 0.0 or hill_radius_m <= 0.0:
        raise ValueError("hill_count and hill_radius_m must be positive; height cannot be negative")
    x_mesh, y_mesh = _coordinate_mesh(grid)
    values = np.full(x_mesh.shape, base_elevation_m, dtype=np.float64)
    bounds = grid.bounds
    random = np.random.default_rng(seed)
    centers_x = random.uniform(bounds.min_x_m, bounds.max_x_m, hill_count)
    centers_y = random.uniform(bounds.min_y_m, bounds.max_y_m, hill_count)
    heights = random.uniform(0.5 * hill_height_m, hill_height_m, hill_count)
    radii = random.uniform(0.6 * hill_radius_m, 1.4 * hill_radius_m, hill_count)
    for center_x, center_y, height, radius in zip(
        centers_x, centers_y, heights, radii, strict=True
    ):
        squared_distance = (x_mesh - center_x) ** 2 + (y_mesh - center_y) ** 2
        values += height * np.exp(-squared_distance / (2.0 * radius**2))
    return Heightmap(values=values.astype(dtype), grid=grid)


def _oriented_distance(
    grid: TerrainGridSpec, *, angle_rad: float, offset_m: float
) -> np.ndarray:
    x_mesh, y_mesh = _coordinate_mesh(grid)
    bounds = grid.bounds
    center_x = (bounds.min_x_m + bounds.max_x_m) / 2.0
    center_y = (bounds.min_y_m + bounds.max_y_m) / 2.0
    normal_x = -sin(angle_rad)
    normal_y = cos(angle_rad)
    return (x_mesh - center_x) * normal_x + (y_mesh - center_y) * normal_y - offset_m


def generate_valley(
    grid: TerrainGridSpec,
    *,
    base_elevation_m: float = 40.0,
    depth_m: float = 30.0,
    width_m: float = 300.0,
    angle_rad: float = 0.0,
    offset_m: float = 0.0,
    dtype: np.dtype[Any] | type[np.floating[Any]] = np.float32,
) -> Heightmap:
    if depth_m < 0.0 or width_m <= 0.0:
        raise ValueError("valley depth cannot be negative and width_m must be positive")
    distance = _oriented_distance(grid, angle_rad=angle_rad, offset_m=offset_m)
    values = base_elevation_m - depth_m * np.exp(-(distance**2) / (2.0 * width_m**2))
    return Heightmap(values=values.astype(dtype), grid=grid)


def generate_ridge(
    grid: TerrainGridSpec,
    *,
    base_elevation_m: float = 0.0,
    height_m: float = 40.0,
    width_m: float = 250.0,
    angle_rad: float = 0.0,
    offset_m: float = 0.0,
    dtype: np.dtype[Any] | type[np.floating[Any]] = np.float32,
) -> Heightmap:
    if height_m < 0.0 or width_m <= 0.0:
        raise ValueError("ridge height cannot be negative and width_m must be positive")
    distance = _oriented_distance(grid, angle_rad=angle_rad, offset_m=offset_m)
    values = base_elevation_m + height_m * np.exp(-(distance**2) / (2.0 * width_m**2))
    return Heightmap(values=values.astype(dtype), grid=grid)


def generate_terrain(
    kind: TerrainKind | str,
    grid: TerrainGridSpec,
    *,
    parameters: dict[str, Any] | None = None,
    seed: int = 0,
) -> Heightmap:
    terrain_kind = TerrainKind(kind)
    generator_parameters = dict(parameters or {})
    if terrain_kind is TerrainKind.FLAT:
        return generate_flat(grid, **generator_parameters)
    if terrain_kind is TerrainKind.HILLS:
        return generate_hills(grid, seed=seed, **generator_parameters)
    if terrain_kind is TerrainKind.VALLEY:
        return generate_valley(grid, **generator_parameters)
    return generate_ridge(grid, **generator_parameters)


def combine_heightmaps(
    heightmaps: tuple[Heightmap, ...], *, weights: tuple[float, ...] | None = None
) -> Heightmap:
    if not heightmaps:
        raise ValueError("at least one heightmap is required")
    reference_grid = heightmaps[0].grid
    if any(heightmap.grid != reference_grid for heightmap in heightmaps[1:]):
        raise ValueError("all heightmaps must use the same grid")
    effective_weights = weights or tuple(1.0 for _ in heightmaps)
    if len(effective_weights) != len(heightmaps):
        raise ValueError("weights must match the number of heightmaps")
    values = sum(
        weight * heightmap.values.astype(np.float64)
        for weight, heightmap in zip(effective_weights, heightmaps, strict=True)
    )
    return Heightmap(values=np.asarray(values, dtype=np.float32), grid=reference_grid)

