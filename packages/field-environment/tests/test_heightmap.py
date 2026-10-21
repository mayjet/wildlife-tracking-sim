from __future__ import annotations

import numpy as np
import pytest

from field_environment import Heightmap, TerrainGridSpec


def test_grid_extent_and_cell_centers_are_consistent() -> None:
    grid = TerrainGridSpec.from_extent(
        30.0, 20.0, 10.0, min_x_m=100.0, min_y_m=200.0
    )
    heightmap = Heightmap(
        values=np.array([[1.0, 2.0, 3.0], [4.0, 5.0, 6.0]], dtype=np.float32),
        grid=grid,
    )
    assert heightmap.values.shape == (2, 3)
    assert heightmap.cell_center(0, 0).model_dump() == {"x_m": 105.0, "y_m": 205.0}
    assert heightmap.cell_center(2, 1).model_dump() == {"x_m": 125.0, "y_m": 215.0}
    assert heightmap.elevation_at(100.0, 200.0) == 1.0
    assert heightmap.elevation_at(129.999, 219.999) == 6.0


@pytest.mark.parametrize("coordinate", [(99.99, 205.0), (130.0, 205.0), (105.0, 220.0)])
def test_heightmap_rejects_out_of_range_coordinates(coordinate: tuple[float, float]) -> None:
    grid = TerrainGridSpec.from_extent(30.0, 20.0, 10.0, min_x_m=100.0, min_y_m=200.0)
    heightmap = Heightmap(values=np.zeros((2, 3), dtype=np.float32), grid=grid)
    with pytest.raises(IndexError):
        heightmap.elevation_at(*coordinate)


def test_grid_requires_extent_divisible_by_cell_size() -> None:
    with pytest.raises(ValueError):
        TerrainGridSpec.from_extent(31.0, 20.0, 10.0)


def test_heightmap_rejects_wrong_shape_and_dtype(grid: TerrainGridSpec) -> None:
    with pytest.raises(ValueError):
        Heightmap(values=np.zeros((1, 1), dtype=np.float32), grid=grid)
    with pytest.raises(TypeError):
        Heightmap(
            values=np.zeros((grid.height_cells, grid.width_cells), dtype=np.int16),
            grid=grid,
        )

