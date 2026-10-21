from __future__ import annotations

from matplotlib import pyplot as plt

from field_environment import plot_terrain_2d


def test_plot_contains_elevation_and_boundary(environment_case) -> None:
    figure, axes = plot_terrain_2d(
        environment_case.heightmap,
        environment_case.farm_boundary,
    )
    assert axes.get_xlabel() == "x / East (m)"
    assert axes.get_ylabel() == "y / North (m)"
    assert len(axes.images) == 1
    assert len(axes.lines) == 1
    plt.close(figure)

