from __future__ import annotations

from matplotlib import pyplot as plt
from matplotlib.axes import Axes
from matplotlib.figure import Figure

from ..farm.boundary import FarmBoundary
from ..terrain.heightmap import Heightmap


def plot_terrain_2d(
    heightmap: Heightmap,
    farm_boundary: FarmBoundary | None = None,
    *,
    ax: Axes | None = None,
    title: str = "Terrain elevation",
) -> tuple[Figure, Axes]:
    if ax is None:
        figure, axes = plt.subplots(figsize=(7, 6), constrained_layout=True)
    else:
        axes = ax
        figure = axes.figure
    bounds = heightmap.bounds
    image = axes.imshow(
        heightmap.values,
        origin="lower",
        extent=(bounds.min_x_m, bounds.max_x_m, bounds.min_y_m, bounds.max_y_m),
        cmap="terrain",
        aspect="equal",
    )
    figure.colorbar(image, ax=axes, label="Elevation (m)")
    if farm_boundary is not None:
        x_coordinates, y_coordinates = farm_boundary.polygon.exterior.xy
        axes.plot(x_coordinates, y_coordinates, color="red", linewidth=2, label="Farm boundary")
        axes.legend()
    axes.set_xlabel("x / East (m)")
    axes.set_ylabel("y / North (m)")
    axes.set_title(title)
    return figure, axes

