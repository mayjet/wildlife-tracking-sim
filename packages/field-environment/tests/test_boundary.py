from __future__ import annotations

import pytest
from shapely.geometry import Polygon

from field_environment import FarmBoundary, TerrainGridSpec


def test_boundary_validates_and_round_trips_geojson(grid: TerrainGridSpec) -> None:
    boundary = FarmBoundary.rectangle(
        min_x_m=10.0,
        min_y_m=10.0,
        max_x_m=190.0,
        max_y_m=110.0,
        coordinate_system_name="test-local-enu",
    )
    boundary.validate_within(grid.bounds)
    restored = FarmBoundary.from_geojson(boundary.to_geojson())
    assert restored.coordinate_system_name == boundary.coordinate_system_name
    assert restored.polygon.equals_exact(boundary.polygon, tolerance=0.0)


def test_invalid_polygon_is_rejected() -> None:
    bow_tie = Polygon([(0.0, 0.0), (2.0, 2.0), (0.0, 2.0), (2.0, 0.0)])
    with pytest.raises(ValueError):
        FarmBoundary(polygon=bow_tie, coordinate_system_name="local")


def test_boundary_outside_terrain_is_rejected(grid: TerrainGridSpec) -> None:
    boundary = FarmBoundary.rectangle(
        min_x_m=-1.0,
        min_y_m=0.0,
        max_x_m=100.0,
        max_y_m=100.0,
        coordinate_system_name="test-local-enu",
    )
    with pytest.raises(ValueError):
        boundary.validate_within(grid.bounds)

