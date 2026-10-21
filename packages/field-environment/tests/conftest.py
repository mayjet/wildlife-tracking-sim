from __future__ import annotations

import pytest

from field_environment import (
    FarmBoundary,
    TerrainGridSpec,
    TerrainKind,
    create_synthetic_case,
)


@pytest.fixture
def grid() -> TerrainGridSpec:
    return TerrainGridSpec.from_extent(200.0, 120.0, 10.0)


@pytest.fixture
def environment_case(grid: TerrainGridSpec):
    case_id = "phase2-test"
    boundary = FarmBoundary.rectangle(
        min_x_m=20.0,
        min_y_m=20.0,
        max_x_m=180.0,
        max_y_m=100.0,
        coordinate_system_name=f"{case_id}-local-enu",
    )
    return create_synthetic_case(
        case_id=case_id,
        terrain_kind=TerrainKind.HILLS,
        grid=grid,
        farm_boundary=boundary,
        generation_parameters={
            "base_elevation_m": 5.0,
            "hill_count": 3,
            "hill_height_m": 12.0,
            "hill_radius_m": 35.0,
        },
        seed=42,
    )

