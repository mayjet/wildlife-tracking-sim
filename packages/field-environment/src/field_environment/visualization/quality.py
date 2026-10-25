from __future__ import annotations

import numpy as np
from matplotlib import pyplot as plt
from matplotlib.colors import LightSource
from matplotlib.figure import Figure

from ..case.models import EnvironmentCase
from ..terrain.quality import slope_degrees


def terrain_extent(environment_case: EnvironmentCase) -> tuple[float, float, float, float]:
    bounds = environment_case.heightmap.bounds
    return bounds.min_x_m, bounds.max_x_m, bounds.min_y_m, bounds.max_y_m


def _finish_axis(axis, title: str) -> None:
    axis.set_title(title)
    axis.set_xlabel("x / East (m)")
    axis.set_ylabel("y / North (m)")
    axis.set_aspect("equal")


# 地形の標高を独立した図として表示する．
def plot_elevation(environment_case: EnvironmentCase) -> tuple[Figure, object]:
    figure, axis = plt.subplots(figsize=(8, 7), constrained_layout=True)
    image = axis.imshow(
        environment_case.heightmap.values,
        origin="lower",
        extent=terrain_extent(environment_case),
        cmap="terrain",
    )
    figure.colorbar(image, ax=axis, label="Elevation (m)")
    _finish_axis(axis, "Elevation in the Case coordinate system")
    return figure, axis


# 地形の陰影を独立した図として表示する．
def plot_hillshade(environment_case: EnvironmentCase) -> tuple[Figure, object]:
    heightmap = environment_case.heightmap
    hillshade = LightSource(azdeg=315, altdeg=45).hillshade(
        heightmap.values,
        vert_exag=1.0,
        dx=heightmap.grid.cell_size_m,
        dy=heightmap.grid.cell_size_m,
    )
    figure, axis = plt.subplots(figsize=(8, 7), constrained_layout=True)
    axis.imshow(hillshade, origin="lower", extent=terrain_extent(environment_case), cmap="gray")
    _finish_axis(axis, "Terrain hillshade")
    return figure, axis


# 地形の傾斜角を独立した図として表示する．
def plot_slope(environment_case: EnvironmentCase) -> tuple[Figure, object]:
    slopes = slope_degrees(
        environment_case.heightmap.values,
        environment_case.heightmap.grid.cell_size_m,
    )
    figure, axis = plt.subplots(figsize=(8, 7), constrained_layout=True)
    image = axis.imshow(
        slopes,
        origin="lower",
        extent=terrain_extent(environment_case),
        cmap="magma",
    )
    figure.colorbar(image, ax=axis, label="Slope (degrees)")
    _finish_axis(axis, "Terrain slope")
    return figure, axis


# 標高，陰影，傾斜を一覧表示する．
def plot_terrain_quality(environment_case: EnvironmentCase) -> tuple[Figure, np.ndarray]:
    heightmap = environment_case.heightmap
    slopes = slope_degrees(heightmap.values, heightmap.grid.cell_size_m)
    hillshade = LightSource(azdeg=315, altdeg=45).hillshade(
        heightmap.values,
        vert_exag=1.0,
        dx=heightmap.grid.cell_size_m,
        dy=heightmap.grid.cell_size_m,
    )
    figure, axes = plt.subplots(1, 3, figsize=(15, 4.5), constrained_layout=True)
    elevation = axes[0].imshow(
        heightmap.values, origin="lower", extent=terrain_extent(environment_case), cmap="terrain"
    )
    figure.colorbar(elevation, ax=axes[0], label="Elevation (m)")
    axes[0].set_title("Elevation")
    axes[1].imshow(hillshade, origin="lower", extent=terrain_extent(environment_case), cmap="gray")
    axes[1].set_title("Hillshade")
    slope_image = axes[2].imshow(
        slopes, origin="lower", extent=terrain_extent(environment_case), cmap="magma"
    )
    figure.colorbar(slope_image, ax=axes[2], label="Slope (degrees)")
    axes[2].set_title("Slope")
    for axis in axes:
        axis.set_xlabel("x / East (m)")
        axis.set_ylabel("y / North (m)")
    return figure, axes


def plot_elevation_comparison(
    left: EnvironmentCase,
    right: EnvironmentCase,
) -> tuple[Figure, np.ndarray]:
    if left.heightmap.grid != right.heightmap.grid:
        raise ValueError("elevation comparison requires matching local grids")
    difference = left.heightmap.values - right.heightmap.values
    figure, axes = plt.subplots(1, 3, figsize=(15, 4.5), constrained_layout=True)
    for axis, values, title in (
        (axes[0], left.heightmap.values, left.provenance.source if left.provenance else "left"),
        (axes[1], right.heightmap.values, right.provenance.source if right.provenance else "right"),
        (axes[2], difference, "left - right (m)"),
    ):
        image = axis.imshow(values, origin="lower", extent=terrain_extent(left), cmap="terrain")
        figure.colorbar(image, ax=axis)
        axis.set_title(title)
    return figure, axes
