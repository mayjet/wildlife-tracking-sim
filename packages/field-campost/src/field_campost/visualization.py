from __future__ import annotations

from matplotlib.axes import Axes
from matplotlib.figure import Figure
from shepherd_contracts import CameraLayout

from field_environment import FarmBoundary, Heightmap, plot_terrain_2d

from .cameras import camera_forward_vector


def plot_camera_layout_2d(
    heightmap: Heightmap,
    farm_boundary: FarmBoundary,
    layout: CameraLayout,
    *,
    ax: Axes | None = None,
    title: str = "Terrain and fixed cameras",
) -> tuple[Figure, Axes]:
    figure, axes = plot_terrain_2d(heightmap, farm_boundary, ax=ax, title=title)
    arrow_length = max(heightmap.width_m, heightmap.height_m) * 0.05
    for camera in layout.cameras:
        direction = camera_forward_vector(camera)
        axes.scatter(camera.position.x_m, camera.position.y_m, marker="^", color="black")
        axes.arrow(
            camera.position.x_m,
            camera.position.y_m,
            direction[0] * arrow_length,
            direction[1] * arrow_length,
            color="black",
            width=arrow_length * 0.02,
            length_includes_head=True,
        )
        axes.annotate(camera.camera_id, (camera.position.x_m, camera.position.y_m))
    return figure, axes
