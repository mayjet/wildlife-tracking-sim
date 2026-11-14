from __future__ import annotations

import numpy as np
from matplotlib import pyplot as plt
from matplotlib.axes import Axes
from matplotlib.figure import Figure
from mpl_toolkits.mplot3d.art3d import Poly3DCollection
from shapely.geometry import shape
from shepherd_contracts import CameraLayout, ObservationPointLayout

from field_environment import (
    EnvironmentCase,
    FarmBoundary,
    Heightmap,
    plot_terrain_2d,
    scene_crop_geometry,
)

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


def plot_observation_point_layout_2d(
    environment_case: EnvironmentCase,
    layout: ObservationPointLayout,
    *,
    ax: Axes | None = None,
) -> tuple[Figure, Axes]:
    figure, axes = plot_terrain_2d(
        environment_case.heightmap,
        environment_case.farm_boundary,
        ax=ax,
        title=f"Observation points: {layout.layout_id}",
    )
    if layout.points:
        axes.scatter(
            [point.position.x_m for point in layout.points],
            [point.position.y_m for point in layout.points],
            marker="^",
            s=18,
            color="black",
            label=f"Observation points ({len(layout.points)})",
        )
        axes.legend()
    return figure, axes


# 地形と建物の簡易3D形状をNotebook確認用に表示する．
def plot_environment_3d(
    environment_case: EnvironmentCase,
    layout: CameraLayout,
    *,
    maximum_terrain_samples: int = 180,
    focus_on_facilities: bool = False,
    focus_padding_m: float = 100.0,
    elevation_deg: float = 32.0,
    azimuth_deg: float = -55.0,
) -> tuple[Figure, object]:
    heightmap = environment_case.heightmap
    view_bounds = scene_crop_geometry(environment_case).bounds
    if (
        focus_on_facilities
        and environment_case.facility_buildings is not None
        and environment_case.facility_buildings.status.value == "available"
    ):
        facility_bounds = [
            shape(feature["geometry"]).bounds
            for feature in environment_case.facility_buildings.features
        ]
        view_bounds = (
            max(heightmap.bounds.min_x_m, min(value[0] for value in facility_bounds) - focus_padding_m),
            max(heightmap.bounds.min_y_m, min(value[1] for value in facility_bounds) - focus_padding_m),
            min(heightmap.bounds.max_x_m, max(value[2] for value in facility_bounds) + focus_padding_m),
            min(heightmap.bounds.max_y_m, max(value[3] for value in facility_bounds) + focus_padding_m),
        )
    all_x_coordinates = heightmap.grid.origin.x_m + np.arange(
        heightmap.grid.width_cells
    ) * heightmap.grid.cell_size_m
    all_y_coordinates = heightmap.grid.origin.y_m + np.arange(
        heightmap.grid.height_cells
    ) * heightmap.grid.cell_size_m
    x_indices = np.flatnonzero(
        (all_x_coordinates >= view_bounds[0]) & (all_x_coordinates <= view_bounds[2])
    )
    y_indices = np.flatnonzero(
        (all_y_coordinates >= view_bounds[1]) & (all_y_coordinates <= view_bounds[3])
    )
    step = max(
        1,
        int(np.ceil(max(len(x_indices), len(y_indices)) / maximum_terrain_samples)),
    )
    x_indices = x_indices[::step]
    y_indices = y_indices[::step]
    x_coordinates = all_x_coordinates[x_indices]
    y_coordinates = all_y_coordinates[y_indices]
    x_mesh, y_mesh = np.meshgrid(x_coordinates, y_coordinates)
    z_mesh = heightmap.values[np.ix_(y_indices, x_indices)]
    figure = plt.figure(figsize=(11, 8), constrained_layout=True)
    axis = figure.add_subplot(111, projection="3d")
    axis.plot_surface(
        x_mesh,
        y_mesh,
        z_mesh,
        cmap="terrain",
        linewidth=0,
        antialiased=False,
        alpha=0.8,
    )

    def add_layer(layer, color: str) -> None:
        if layer is None or layer.status.value != "available":
            return
        for feature in layer.features:
            geometry = shape(feature["geometry"])
            polygons = geometry.geoms if geometry.geom_type == "MultiPolygon" else (geometry,)
            properties = feature.get("properties") or {}
            height_m = (
                properties.get("height_m")
                or properties.get("assumed_height_m")
                or layer.assumed_height_m
            )
            if height_m is None:
                continue
            for polygon in polygons:
                coordinates = np.asarray(polygon.exterior.coords[:-1], dtype=float)
                if len(coordinates) < 3:
                    continue
                if not shape(feature["geometry"]).intersects(scene_crop_geometry(environment_case)):
                    continue
                point = polygon.representative_point()
                try:
                    ground_z = heightmap.surface_elevation_at(point.x, point.y)
                except IndexError:
                    continue
                ground = [ground_z] * len(coordinates)
                bottom = [(x, y, z) for (x, y), z in zip(coordinates, ground)]
                top = [(x, y, z + height_m) for (x, y), z in zip(coordinates, ground)]
                faces = [bottom[::-1], top]
                for index in range(len(coordinates)):
                    next_index = (index + 1) % len(coordinates)
                    faces.append(
                        [bottom[index], bottom[next_index], top[next_index], top[index]]
                    )
                axis.add_collection3d(
                    Poly3DCollection(
                        faces,
                        facecolors=color,
                        edgecolors=color,
                        linewidths=0.3,
                        alpha=0.9,
                    )
                )

    add_layer(environment_case.buildings, "gray")
    add_layer(environment_case.facility_buildings, "firebrick")

    for camera in layout.cameras:
        axis.scatter(
            camera.position.x_m,
            camera.position.y_m,
            camera.position.z_m,
            color="black",
            marker="^",
        )
    axis.set_xlabel("x / East (m)")
    axis.set_ylabel("y / North (m)")
    axis.set_zlabel("z / Elevation (m)")
    axis.set_title(
        "Facility buildings and local terrain"
        if focus_on_facilities
        else "Terrain and extruded building footprints"
    )
    axis.set_xlim(view_bounds[0], view_bounds[2])
    axis.set_ylim(view_bounds[1], view_bounds[3])
    axis.view_init(elev=elevation_deg, azim=azimuth_deg)
    return figure, axis
