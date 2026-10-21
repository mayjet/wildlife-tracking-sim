from __future__ import annotations

import numpy as np
import pytest

from field_environment import (
    TerrainGridSpec,
    combine_heightmaps,
    generate_flat,
    generate_hills,
    generate_ridge,
    generate_valley,
)


def test_flat_has_constant_elevation(grid: TerrainGridSpec) -> None:
    terrain = generate_flat(grid, elevation_m=12.5)
    assert terrain.values.dtype == np.float32
    np.testing.assert_array_equal(terrain.values, np.full(terrain.values.shape, 12.5))


@pytest.mark.parametrize("generator", [generate_hills, generate_valley, generate_ridge])
def test_terrain_generators_return_finite_expected_shape(generator, grid: TerrainGridSpec) -> None:
    if generator is generate_hills:
        terrain = generator(grid, seed=7, hill_radius_m=30.0)
    else:
        terrain = generator(grid, width_m=30.0)
    assert terrain.values.shape == (grid.height_cells, grid.width_cells)
    assert np.isfinite(terrain.values).all()
    assert np.ptp(terrain.values) > 0.0


def test_hills_are_reproducible(grid: TerrainGridSpec) -> None:
    first = generate_hills(grid, seed=123, hill_count=4, hill_radius_m=25.0)
    second = generate_hills(grid, seed=123, hill_count=4, hill_radius_m=25.0)
    different = generate_hills(grid, seed=124, hill_count=4, hill_radius_m=25.0)
    np.testing.assert_array_equal(first.values, second.values)
    assert not np.array_equal(first.values, different.values)


def test_combine_heightmaps_supports_composition(grid: TerrainGridSpec) -> None:
    flat = generate_flat(grid, elevation_m=5.0)
    ridge = generate_ridge(grid, height_m=10.0, width_m=30.0)
    combined = combine_heightmaps((flat, ridge), weights=(1.0, 0.5))
    np.testing.assert_allclose(combined.values, flat.values + 0.5 * ridge.values)


def test_standard_three_kilometer_extent_can_be_generated() -> None:
    grid = TerrainGridSpec.from_extent(3_000.0, 3_000.0, 10.0)
    terrain = generate_flat(grid, elevation_m=2.0)
    assert terrain.values.shape == (300, 300)
    assert terrain.values.nbytes < 1_000_000
