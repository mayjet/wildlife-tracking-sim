from __future__ import annotations

import sys
from pathlib import Path

import pytest

REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
for source_root in (
    REPOSITORY_ROOT / "libs" / "shepherd-contracts" / "src",
    REPOSITORY_ROOT / "packages" / "field-environment" / "src",
    REPOSITORY_ROOT / "packages" / "field-sim" / "src",
):
    sys.path.insert(0, str(source_root))

from field_environment import FarmBoundary, TerrainGridSpec, create_synthetic_case, save_case


@pytest.fixture
def simulation_case():
    case_id = "simulation-case"
    grid = TerrainGridSpec.from_extent(
        width_m=100.0,
        height_m=100.0,
        cell_size_m=10.0,
        min_x_m=-50.0,
        min_y_m=-50.0,
    )
    boundary = FarmBoundary.rectangle(
        min_x_m=-30.0,
        min_y_m=-30.0,
        max_x_m=30.0,
        max_y_m=30.0,
        coordinate_system_name=f"{case_id}-local-enu",
    )
    return create_synthetic_case(
        case_id=case_id,
        terrain_kind="ridge",
        grid=grid,
        farm_boundary=boundary,
        generation_parameters={
            "base_elevation_m": 5.0,
            "height_m": 20.0,
            "width_m": 30.0,
            "angle_rad": 0.0,
        },
        seed=17,
    )


@pytest.fixture
def saved_case(tmp_path, simulation_case):
    cases_root = tmp_path / "cases"
    save_case(simulation_case, cases_root)
    return cases_root, simulation_case
