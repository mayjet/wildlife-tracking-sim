from __future__ import annotations

from matplotlib import pyplot as plt
from matplotlib.axes import Axes
from matplotlib.figure import Figure

from field_environment import EnvironmentCase, plot_terrain_2d

from .simulator import SimulationResult


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
