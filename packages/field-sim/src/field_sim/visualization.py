from __future__ import annotations

from matplotlib import pyplot as plt
from matplotlib.axes import Axes
from matplotlib.colors import BoundaryNorm, ListedColormap
from matplotlib.figure import Figure
import numpy as np

from field_environment import EnvironmentCase, plot_terrain_2d

from .simulator import SimulationResult
from .observations import (
    VisibilityClass,
    VisibilityFailure,
    VisibilityMap,
    as_binary_visibility_map,
)


def plot_ground_truth_trajectory(
    environment_case: EnvironmentCase,
    result: SimulationResult,
    *,
    ax: Axes | None = None,
) -> tuple[Figure, Axes]:
    figure, axes = plot_terrain_2d(
        environment_case.heightmap,
        environment_case.farm_boundary,
        ax=ax,
        title="Ground-truth deer trajectory",
    )
    positions = [frame.states[0].position for frame in result.frames]
    axes.plot(
        [position.x_m for position in positions],
        [position.y_m for position in positions],
        color="magenta",
        marker="o",
        markersize=3,
        label="Ground Truth",
    )
    axes.legend()
    return figure, axes


def plot_visibility_map(
    environment_case: EnvironmentCase,
    visibility_map: VisibilityMap,
    *,
    ax: Axes | None = None,
) -> tuple[Figure, Axes]:
    figure, axes = plot_terrain_2d(
        environment_case.heightmap,
        environment_case.farm_boundary,
        ax=ax,
        title="Deer-height camera visibility",
    )
    if len(visibility_map.x_centers_m) and len(visibility_map.y_centers_m):
        half = visibility_map.cell_size_m / 2.0
        extent = (
            visibility_map.x_centers_m[0] - half,
            visibility_map.x_centers_m[-1] + half,
            visibility_map.y_centers_m[0] - half,
            visibility_map.y_centers_m[-1] + half,
        )
        image = axes.imshow(
            visibility_map.classes,
            origin="lower",
            extent=extent,
            interpolation="nearest",
            vmin=int(VisibilityClass.OUTSIDE_AREA),
            vmax=int(VisibilityClass.FULLY_VISIBLE),
            cmap="RdYlGn",
            alpha=0.55,
        )
        figure.colorbar(image, ax=axes, label="0 outside, 1 hidden, 2 partial, 3 full")
    return figure, axes


# 正式評価を可視・不可視・農場外の3色へ整理して表示する．
def plot_binary_visibility_map(
    environment_case: EnvironmentCase,
    visibility_map: VisibilityMap,
    *,
    ax: Axes | None = None,
) -> tuple[Figure, Axes]:
    visibility_map = as_binary_visibility_map(visibility_map)
    figure, axes = plot_terrain_2d(
        environment_case.heightmap,
        environment_case.farm_boundary,
        ax=ax,
        title="Formal 1 m full-body visibility",
    )
    if len(visibility_map.x_centers_m) and len(visibility_map.y_centers_m):
        half = visibility_map.cell_size_m / 2.0
        extent = (
            visibility_map.x_centers_m[0] - half,
            visibility_map.x_centers_m[-1] + half,
            visibility_map.y_centers_m[0] - half,
            visibility_map.y_centers_m[-1] + half,
        )
        binary_classes = np.zeros(visibility_map.classes.shape, dtype=np.uint8)
        inside = visibility_map.classes != VisibilityClass.OUTSIDE_AREA
        visible = visibility_map.classes == VisibilityClass.FULLY_VISIBLE
        binary_classes[inside] = 1
        binary_classes[visible] = 2
        colors = ListedColormap(("#d9d9d9", "#d73027", "#1a9850"))
        norm = BoundaryNorm((-0.5, 0.5, 1.5, 2.5), colors.N)
        image = axes.imshow(
            binary_classes,
            origin="lower",
            extent=extent,
            interpolation="nearest",
            cmap=colors,
            norm=norm,
            alpha=0.9,
        )
        colorbar = figure.colorbar(image, ax=axes, ticks=(0, 1, 2))
        colorbar.ax.set_yticklabels(("Outside farm", "Not visible", "Visible"))
        inside_count = int(inside.sum())
        visible_count = int(visible.sum())
        visible_rate = visible_count / inside_count if inside_count else 0.0
        axes.text(
            0.02,
            0.98,
            (
                "Rule: feet, torso and head visible from one camera\n"
                f"Visible: {visible_count:,} / {inside_count:,} cells ({visible_rate:.1%})"
            ),
            transform=axes.transAxes,
            va="top",
            ha="left",
            fontsize=9,
            bbox={"facecolor": "white", "alpha": 0.85, "edgecolor": "none"},
        )
    return figure, axes


def plot_visibility_failures(
    environment_case: EnvironmentCase,
    visibility_map: VisibilityMap,
    *,
    ax: Axes | None = None,
) -> tuple[Figure, Axes]:
    figure, axes = plot_terrain_2d(
        environment_case.heightmap,
        environment_case.farm_boundary,
        ax=ax,
        title="Primary camera visibility failure",
    )
    if len(visibility_map.x_centers_m) and len(visibility_map.y_centers_m):
        half = visibility_map.cell_size_m / 2.0
        extent = (
            visibility_map.x_centers_m[0] - half,
            visibility_map.x_centers_m[-1] + half,
            visibility_map.y_centers_m[0] - half,
            visibility_map.y_centers_m[-1] + half,
        )
        image = axes.imshow(
            visibility_map.failure_codes,
            origin="lower",
            extent=extent,
            interpolation="nearest",
            vmin=0,
            vmax=len(VisibilityFailure) - 1,
            cmap="tab10",
            alpha=0.6,
        )
        labels = ", ".join(
            f"{index} {failure.value.lower()}"
            for index, failure in enumerate(VisibilityFailure)
        )
        figure.colorbar(image, ax=axes, label=labels)
    return figure, axes
