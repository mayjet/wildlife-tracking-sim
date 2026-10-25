from __future__ import annotations

import numpy as np
from matplotlib import pyplot as plt
from matplotlib.colors import BoundaryNorm, ListedColormap
from matplotlib.figure import Figure
from shapely.geometry import shape

from ..case.models import EnvironmentCase
from ..environment_detection import WORLD_COVER_CLASSES
from ..features import FeatureLayerStatus
from .quality import terrain_extent
from .terrain_2d import plot_terrain_2d


def _finish(axis, title: str) -> None:
    axis.set_title(title)
    axis.set_xlabel("x / East (m)")
    axis.set_ylabel("y / North (m)")
    axis.set_aspect("equal")
    handles, _ = axis.get_legend_handles_labels()
    if handles:
        axis.legend(loc="best")


def _draw_layer(
    axis,
    layer,
    *,
    color: str,
    label: str,
    alpha: float = 0.35,
    outline_only: bool = False,
    annotate_property: str | None = None,
) -> None:
    if layer is None or layer.status is not FeatureLayerStatus.AVAILABLE:
        return
    first = True
    for feature in layer.features:
        geometry = shape(feature["geometry"])
        polygons = geometry.geoms if geometry.geom_type == "MultiPolygon" else (geometry,)
        for polygon in polygons:
            x_coordinates, y_coordinates = polygon.exterior.xy
            if outline_only:
                axis.plot(
                    x_coordinates,
                    y_coordinates,
                    color=color,
                    linewidth=2,
                    label=label if first else None,
                )
            else:
                axis.fill(
                    x_coordinates,
                    y_coordinates,
                    color=color,
                    alpha=alpha,
                    label=label if first else None,
                )
            if annotate_property is not None:
                value = (feature.get("properties") or {}).get(annotate_property)
                if value is not None:
                    axis.text(
                        polygon.centroid.x,
                        polygon.centroid.y,
                        str(value),
                        ha="center",
                        va="center",
                        fontsize=8,
                        bbox={"facecolor": "white", "alpha": 0.7, "edgecolor": "none"},
                    )
            first = False


def _imagery_background(environment_case: EnvironmentCase, axis) -> None:
    if environment_case.imagery is None:
        return
    bounds = environment_case.imagery.grid.bounds
    axis.imshow(
        environment_case.imagery.values,
        origin="lower",
        extent=(bounds.min_x_m, bounds.max_x_m, bounds.min_y_m, bounds.max_y_m),
    )


def _overlay_figure(environment_case: EnvironmentCase, title: str) -> tuple[Figure, object]:
    figure, axis = plt.subplots(figsize=(8, 7), constrained_layout=True)
    _imagery_background(environment_case, axis)
    if environment_case.imagery is None:
        extent = terrain_extent(environment_case)
        axis.set_xlim(extent[0], extent[1])
        axis.set_ylim(extent[2], extent[3])
    _finish(axis, title)
    return figure, axis


# 取得した衛星・航空画像をCase座標で表示する．
def plot_satellite_imagery(environment_case: EnvironmentCase) -> tuple[Figure, object]:
    if environment_case.imagery is None:
        raise ValueError("Case has no satellite imagery")
    figure, axis = _overlay_figure(environment_case, "RGB imagery")
    _finish(axis, f"RGB imagery — {environment_case.imagery.source}")
    return figure, axis


# 土地被覆分類を凡例付きで表示する．
def plot_landcover(environment_case: EnvironmentCase) -> tuple[Figure, object]:
    if environment_case.landcover is None:
        raise ValueError("Case has no land-cover raster")
    class_values = sorted(WORLD_COVER_CLASSES)
    colors = [
        "#000000", "#006400", "#ffbb22", "#ffff4c", "#f096ff", "#fa0000",
        "#b4b4b4", "#f0f0f0", "#0064c8", "#0096a0", "#00cf75", "#fae6a0",
    ]
    boundaries = [0] + [
        (left + right) / 2 for left, right in zip(class_values, class_values[1:])
    ] + [105]
    figure, axis = plt.subplots(figsize=(9, 7), constrained_layout=True)
    image = axis.imshow(
        environment_case.landcover.values,
        origin="lower",
        extent=terrain_extent(environment_case),
        cmap=ListedColormap(colors),
        norm=BoundaryNorm(boundaries, len(colors)),
        interpolation="nearest",
    )
    colorbar = figure.colorbar(image, ax=axis, ticks=class_values)
    colorbar.ax.set_yticklabels([WORLD_COVER_CLASSES[value] for value in class_values])
    _finish(axis, f"Land cover — {environment_case.landcover.source}")
    return figure, axis


# 土地被覆から抽出した森林を画像へ重ねる．
def plot_forest_classification(environment_case: EnvironmentCase) -> tuple[Figure, object]:
    figure, axis = _overlay_figure(environment_case, "Forest classification")
    _draw_layer(axis, environment_case.forest, color="darkgreen", label="Forest", alpha=0.45)
    _finish(axis, "Forest classification — ESA WorldCover classes 10 and 95")
    return figure, axis


# 傾斜と建物を除外した開放地候補を表示する．
def plot_open_land_candidates(environment_case: EnvironmentCase) -> tuple[Figure, object]:
    figure, axis = _overlay_figure(environment_case, "Open-land candidates")
    _draw_layer(
        axis,
        environment_case.pasture_candidates,
        color="yellow",
        label="Open-land candidate",
        alpha=0.4,
    )
    _draw_layer(axis, environment_case.buildings, color="black", label="Building", alpha=0.75)
    _finish(axis, "Open land after land-cover, slope, and building exclusion")
    return figure, axis


# 取得した建物外周を採用候補と除外対象に分けて表示する．
def plot_building_footprints(environment_case: EnvironmentCase) -> tuple[Figure, object]:
    figure, axis = _overlay_figure(environment_case, "Building footprints")
    _draw_layer(
        axis,
        environment_case.excluded_buildings or environment_case.buildings,
        color="gray",
        label="Other building",
        alpha=0.6,
    )
    _draw_layer(
        axis,
        environment_case.facility_buildings,
        color="red",
        label="Facility candidate",
        alpha=0.8,
    )
    source = environment_case.buildings.source if environment_case.buildings else "unknown"
    _finish(axis, f"Building footprints and facility candidates — {source}")
    return figure, axis


# 連続性判定後の牧場候補を番号付きで表示する．
def plot_farm_complex_candidates(environment_case: EnvironmentCase) -> tuple[Figure, object]:
    figure, axis = _overlay_figure(environment_case, "Farm-complex candidates")
    _draw_layer(
        axis,
        environment_case.farm_complex_candidates,
        color="orange",
        label="Farm-complex candidate",
        alpha=0.3,
        annotate_property="candidate_id",
    )
    axis.scatter(0.0, 0.0, color="cyan", marker="+", s=120, label="Selection anchor")
    _finish(axis, "Connected open-land blocks; numbers indicate selection order")
    return figure, axis


# 選択された牧場の塊と内部の森林・施設を表示する．
def plot_selected_farm_complex(environment_case: EnvironmentCase) -> tuple[Figure, object]:
    figure, axis = _overlay_figure(environment_case, "Selected farm complex")
    _draw_layer(axis, environment_case.monitoring_area, color="orange", label="Selected block", alpha=0.25)
    _draw_layer(axis, environment_case.forest, color="darkgreen", label="Forest", alpha=0.45)
    _draw_layer(axis, environment_case.facility_buildings, color="red", label="Facility", alpha=0.8)
    _finish(axis, "Selected farm block with retained forest and facility buildings")
    return figure, axis


# 実験用の監視範囲と確定済み牧場境界を比較する．
def plot_monitoring_boundary(environment_case: EnvironmentCase) -> tuple[Figure, object]:
    figure, axis = _overlay_figure(environment_case, "Experimental monitoring boundary")
    _draw_layer(
        axis,
        environment_case.monitoring_area,
        color="orange",
        label="Detected monitoring area",
        outline_only=True,
    )
    boundary_x, boundary_y = environment_case.farm_boundary.polygon.exterior.xy
    axis.plot(boundary_x, boundary_y, color="red", linewidth=2, label="Saved farm boundary")
    _draw_layer(axis, environment_case.facility_buildings, color="black", label="Facility", alpha=0.75)
    _finish(axis, "Monitoring boundary (not camera visibility)")
    return figure, axis


# 地形上で使用する森林，建物，牧草地，監視範囲をまとめて表示する．
def plot_experiment_environment(environment_case: EnvironmentCase) -> tuple[Figure, object]:
    figure, axis = _overlay_figure(environment_case, "Completed experiment environment")
    _draw_layer(axis, environment_case.pasture_candidates, color="gold", label="Open land", alpha=0.2)
    _draw_layer(axis, environment_case.forest, color="darkgreen", label="Forest", alpha=0.45)
    _draw_layer(axis, environment_case.facility_buildings, color="red", label="Facility", alpha=0.85)
    _draw_layer(axis, environment_case.excluded_buildings, color="gray", label="Excluded building", alpha=0.5)
    _draw_layer(
        axis,
        environment_case.monitoring_area,
        color="cyan",
        label="Monitoring boundary",
        outline_only=True,
    )
    _finish(axis, "Experiment environment: forest, buildings, open land, and monitoring area")
    return figure, axis


# 農場境界と，3D生成に用いる矩形クロップ範囲を衛星画像上で比較する．
def plot_scene_crop(environment_case: EnvironmentCase) -> tuple[Figure, object]:
    figure, axis = _overlay_figure(environment_case, "3D scene crop")
    boundary_x, boundary_y = environment_case.farm_boundary.polygon.exterior.xy
    axis.plot(boundary_x, boundary_y, color="red", linewidth=2, label="Saved farm boundary")
    _draw_layer(
        axis,
        environment_case.scene_crop,
        color="cyan",
        label="3D scene crop",
        outline_only=True,
    )
    _finish(axis, "Farm boundary and rectangular 3D scene crop")
    return figure, axis


def plot_environment_features(environment_case: EnvironmentCase) -> tuple[Figure, object]:
    figure, axis = plot_terrain_2d(
        environment_case.heightmap,
        environment_case.farm_boundary,
        title="Terrain, farm boundary, buildings, and forest",
    )
    _draw_layer(axis, environment_case.forest, color="darkgreen", label="Forest")
    _draw_layer(axis, environment_case.buildings, color="black", label="Buildings")
    handles, _ = axis.get_legend_handles_labels()
    if handles:
        axis.legend()
    return figure, axis


def plot_environment_detection(environment_case: EnvironmentCase) -> tuple[Figure, np.ndarray]:
    if environment_case.imagery is None or environment_case.landcover is None:
        raise ValueError("Case has no imagery or landcover detection data")
    figure, axes = plt.subplots(2, 2, figsize=(14, 12), constrained_layout=True)
    _imagery_background(environment_case, axes[0, 0])
    _finish(axes[0, 0], "GSI RGB imagery")
    axes[0, 1].imshow(
        environment_case.landcover.values,
        origin="lower",
        extent=terrain_extent(environment_case),
        cmap="terrain",
        interpolation="nearest",
    )
    _finish(axes[0, 1], "ESA WorldCover")
    _imagery_background(environment_case, axes[1, 0])
    _draw_layer(axes[1, 0], environment_case.forest, color="darkgreen", label="Forest")
    _draw_layer(axes[1, 0], environment_case.buildings, color="black", label="Buildings", alpha=0.7)
    _finish(axes[1, 0], "Forest and acquired buildings")
    _imagery_background(environment_case, axes[1, 1])
    _draw_layer(axes[1, 1], environment_case.pasture_candidates, color="yellow", label="Open land")
    _draw_layer(axes[1, 1], environment_case.monitoring_area, color="red", label="Monitoring area", outline_only=True)
    _finish(axes[1, 1], "Open land and monitoring area")
    return figure, axes
