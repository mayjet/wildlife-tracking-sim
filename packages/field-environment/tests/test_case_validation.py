from __future__ import annotations

import pytest
from pydantic import ValidationError

from field_environment import (
    CaseValidationError,
    FarmBoundary,
    TerrainGridSpec,
    TerrainKind,
    create_synthetic_case,
    load_case,
    save_case,
    validate_case_directory,
    validate_environment_case,
)


@pytest.mark.parametrize("case_id", ["../escape", "/absolute", "contains space", ""])
def test_invalid_case_id_is_rejected(tmp_path, grid: TerrainGridSpec, case_id: str) -> None:
    boundary = FarmBoundary.rectangle(
        min_x_m=10.0,
        min_y_m=10.0,
        max_x_m=100.0,
        max_y_m=100.0,
        coordinate_system_name=f"{case_id}-local-enu",
    )
    with pytest.raises(ValueError):
        environment_case = create_synthetic_case(
            case_id=case_id,
            terrain_kind=TerrainKind.FLAT,
            grid=grid,
            farm_boundary=boundary,
        )
        save_case(environment_case, tmp_path)


def test_case_validation_detects_boundary_outside_grid(grid: TerrainGridSpec) -> None:
    case_id = "outside"
    boundary = FarmBoundary.rectangle(
        min_x_m=-10.0,
        min_y_m=0.0,
        max_x_m=100.0,
        max_y_m=100.0,
        coordinate_system_name=f"{case_id}-local-enu",
    )
    with pytest.raises(CaseValidationError):
        create_synthetic_case(
            case_id=case_id,
            terrain_kind=TerrainKind.FLAT,
            grid=grid,
            farm_boundary=boundary,
        )


def test_case_directory_requires_all_files(tmp_path) -> None:
    case_directory = tmp_path / "incomplete"
    case_directory.mkdir()
    with pytest.raises(CaseValidationError):
        validate_case_directory(case_directory)


def test_loader_rejects_requested_id_mismatch(tmp_path, environment_case) -> None:
    save_case(environment_case, tmp_path)
    with pytest.raises((FileNotFoundError, CaseValidationError)):
        load_case(tmp_path, "another-case")


def test_environment_case_has_valid_contract(environment_case) -> None:
    validate_environment_case(environment_case)
    assert environment_case.case_spec.environment.terrain == "terrain.tif"
    assert environment_case.generation.seed == 42
