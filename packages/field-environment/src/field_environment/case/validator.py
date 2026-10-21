from __future__ import annotations

from pathlib import Path

import numpy as np
from shepherd_contracts import HorizontalAxisDirection, VerticalAxisDirection

from .models import EnvironmentCase


class CaseValidationError(ValueError):
    pass


def _bounds_match(left: object, right: object) -> bool:
    left_values = np.array(
        [left.min_x_m, left.min_y_m, left.max_x_m, left.max_y_m], dtype=float
    )
    right_values = np.array(
        [right.min_x_m, right.min_y_m, right.max_x_m, right.max_y_m], dtype=float
    )
    return bool(np.allclose(left_values, right_values, rtol=0.0, atol=1e-9))


def validate_environment_case(environment_case: EnvironmentCase) -> None:
    errors: list[str] = []
    case_spec = environment_case.case_spec
    coordinate_system = case_spec.coordinate_system
    if coordinate_system.x_axis is not HorizontalAxisDirection.EAST:
        errors.append("Phase 2 heightmaps require x_axis=EAST")
    if coordinate_system.y_axis is not HorizontalAxisDirection.NORTH:
        errors.append("Phase 2 heightmaps require y_axis=NORTH")
    if coordinate_system.z_axis is not VerticalAxisDirection.UP:
        errors.append("Phase 2 heightmaps require z_axis=UP")
    if case_spec.environment.terrain != "terrain.tif":
        errors.append("CaseSpec.environment.terrain must reference terrain.tif")
    if case_spec.farm_boundary.data_ref != "farm_boundary.geojson":
        errors.append("CaseSpec farm boundary must reference farm_boundary.geojson")
    if environment_case.traversability is not None:
        if case_spec.environment.traversability != "traversability.tif":
            errors.append("CaseSpec.environment.traversability must reference traversability.tif")
        if environment_case.traversability.grid != environment_case.heightmap.grid:
            errors.append("traversability grid must match the Heightmap grid")
    for layer_name, layer in (
        ("buildings", environment_case.buildings),
        ("forest", environment_case.forest),
    ):
        if layer is not None and layer.coordinate_system_name != coordinate_system.name:
            errors.append(f"{layer_name} and CaseSpec coordinate systems must match")
    if environment_case.farm_boundary.coordinate_system_name != coordinate_system.name:
        errors.append("farm boundary and CaseSpec coordinate systems must match")
    try:
        environment_case.farm_boundary.validate_within(environment_case.heightmap.bounds)
    except ValueError as error:
        errors.append(str(error))
    if not _bounds_match(case_spec.farm_boundary.bounds, environment_case.farm_boundary.bounds):
        errors.append("CaseSpec farm boundary bounds do not match the Polygon")
    if errors:
        raise CaseValidationError("; ".join(errors))


def validate_case_directory(case_directory: Path) -> None:
    required_files = ("case.yaml", "terrain.tif", "farm_boundary.geojson")
    missing = [name for name in required_files if not (case_directory / name).is_file()]
    if missing:
        raise CaseValidationError(f"missing required Case files: {', '.join(missing)}")
    for directory_name in ("datasets", "runs"):
        if not (case_directory / directory_name).is_dir():
            raise CaseValidationError(f"missing required Case directory: {directory_name}")
