from __future__ import annotations

from pathlib import Path

import numpy as np
from matplotlib import pyplot as plt
from matplotlib.colors import LightSource
from matplotlib.figure import Figure
from shapely.geometry import shape

from ..case.models import EnvironmentCase
from ..features import FeatureLayerStatus
from ..terrain.quality import slope_degrees


def _extent(environment_case: EnvironmentCase) -> tuple[float, float, float, float]:
    bounds = environment_case.heightmap.bounds
    return bounds.min_x_m, bounds.max_x_m, bounds.min_y_m, bounds.max_y_m


def plot_terrain_quality(environment_case: EnvironmentCase) -> tuple[Figure, np.ndarray]:
    heightmap = environment_case.heightmap
    slopes = slope_degrees(heightmap.values, heightmap.grid.cell_size_m)
    light_source = LightSource(azdeg=315, altdeg=45)
    hillshade = light_source.hillshade(
        heightmap.values,
        vert_exag=1.0,
        dx=heightmap.grid.cell_size_m,
        dy=heightmap.grid.cell_size_m,
    )
    figure, axes = plt.subplots(1, 3, figsize=(15, 4.5), constrained_layout=True)
    elevation = axes[0].imshow(
        heightmap.values, origin="lower", extent=_extent(environment_case), cmap="terrain"
    )
    figure.colorbar(elevation, ax=axes[0], label="Elevation (m)")
    axes[0].set_title("Elevation")
    axes[1].imshow(hillshade, origin="lower", extent=_extent(environment_case), cmap="gray")
    axes[1].set_title("Hillshade")
    slope_image = axes[2].imshow(
        slopes, origin="lower", extent=_extent(environment_case), cmap="magma"
    )
    figure.colorbar(slope_image, ax=axes[2], label="Slope (degrees)")
    axes[2].set_title("Slope")
    for axis in axes:
        axis.set_xlabel("x / East (m)")
        axis.set_ylabel("y / North (m)")
    return figure, axes


def plot_environment_features(environment_case: EnvironmentCase) -> tuple[Figure, object]:
    from .terrain_2d import plot_terrain_2d

    figure, axis = plot_terrain_2d(
        environment_case.heightmap,
        environment_case.farm_boundary,
        title="Terrain, farm boundary, buildings, and forest",
    )
    for layer, color, label in (
        (environment_case.forest, "darkgreen", "Forest"),
        (environment_case.buildings, "black", "Buildings"),
    ):
        if layer is None or layer.status is not FeatureLayerStatus.AVAILABLE:
            continue
        first = True
        for feature in layer.features:
            geometry = shape(feature["geometry"])
            polygons = geometry.geoms if geometry.geom_type == "MultiPolygon" else (geometry,)
            for polygon in polygons:
                x, y = polygon.exterior.xy
                axis.fill(x, y, color=color, alpha=0.35, label=label if first else None)
                first = False
    axis.legend()
    return figure, axis


def save_case_previews(environment_case: EnvironmentCase, case_directory: str | Path) -> tuple[Path, ...]:
    destination = Path(case_directory) / "previews"
    destination.mkdir(parents=True, exist_ok=True)
    saved = []
    quality_figure, quality_axes = plot_terrain_quality(environment_case)
    quality_path = destination / "terrain_quality.png"
    quality_figure.savefig(quality_path, dpi=140)
    for axis, filename in zip(
        quality_axes,
        ("elevation.png", "hillshade.png", "slope.png"),
    ):
        extent = axis.get_window_extent().transformed(quality_figure.dpi_scale_trans.inverted())
        path = destination / filename
        quality_figure.savefig(path, dpi=140, bbox_inches=extent.expanded(1.18, 1.22))
        saved.append(path)
    plt.close(quality_figure)
    saved.append(quality_path)
    environment_figure, _ = plot_environment_features(environment_case)
    environment_path = destination / "environment.png"
    environment_figure.savefig(environment_path, dpi=140)
    plt.close(environment_figure)
    saved.append(environment_path)
    origin = environment_case.case_spec.coordinate_system.geodetic_origin
    provenance = environment_case.provenance
    if origin is not None and provenance is not None and provenance.geographic_bounds is not None:
        west, south, east, north = provenance.geographic_bounds
        figure, axis = plt.subplots(figsize=(6, 5), constrained_layout=True)
        axis.plot([west, east, east, west, west], [south, south, north, north, south])
        axis.scatter(origin.longitude_deg, origin.latitude_deg, marker="+", color="red")
        axis.set_xlabel("Longitude (degrees)")
        axis.set_ylabel("Latitude (degrees)")
        axis.set_title("Source location and requested extent")
        location_path = destination / "location.png"
        figure.savefig(location_path, dpi=140)
        plt.close(figure)
        saved.append(location_path)
    return tuple(saved)


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
        image = axis.imshow(values, origin="lower", extent=_extent(left), cmap="terrain")
        figure.colorbar(image, ax=axis)
        axis.set_title(title)
    return figure, axes
