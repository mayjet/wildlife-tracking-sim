from __future__ import annotations

from dataclasses import replace

import numpy as np
import pytest
from shepherd_contracts import Position2D, Velocity2D

from field_environment import (
    FeatureLayerStatus,
    TraversabilityMap,
    TraversabilityValue,
    create_feature_layer,
)
from field_sim import (
    LinearMotion,
    SimulationConfig,
    StationaryMotion,
    TimedWaypoint,
    TrajectoryValidationError,
    WaypointMotion,
    project_to_terrain_surface,
    simulate,
    surface_elevation_at,
)


def _config(case_id: str, motion, *, dataset_id: str = "dataset") -> SimulationConfig:
    return SimulationConfig(
        case_id=case_id,
        dataset_id=dataset_id,
        seed=42,
        duration_s=4.0,
        step_s=1.0,
        motion=motion,
    )


def test_stationary_linear_and_waypoint_time_progression(simulation_case) -> None:
    motions = (
        StationaryMotion(kind="stationary", position=Position2D(x_m=0.0, y_m=0.0)),
        LinearMotion(
            kind="linear",
            start=Position2D(x_m=-10.0, y_m=-10.0),
            velocity=Velocity2D(x_mps=2.0, y_mps=1.0),
        ),
        WaypointMotion(
            kind="waypoints",
            waypoints=(
                TimedWaypoint(timestamp_s=0.0, position=Position2D(x_m=-10.0, y_m=0.0)),
                TimedWaypoint(timestamp_s=2.0, position=Position2D(x_m=0.0, y_m=10.0)),
                TimedWaypoint(timestamp_s=4.0, position=Position2D(x_m=10.0, y_m=0.0)),
            ),
        ),
    )
    for index, motion in enumerate(motions):
        result = simulate(
            simulation_case,
            _config(simulation_case.case_spec.case_id, motion, dataset_id=f"d-{index}"),
        )
        assert [frame.timestamp_s for frame in result.frames] == [0, 1, 2, 3, 4]
        assert all(frame.states[0].position.z_m is not None for frame in result.frames)


def test_surface_height_matches_mesh_triangle_interpolation(simulation_case) -> None:
    heightmap = simulation_case.heightmap
    x_m = heightmap.grid.origin.x_m + 2.25 * heightmap.grid.cell_size_m
    y_m = heightmap.grid.origin.y_m + 3.75 * heightmap.grid.cell_size_m
    elevation = surface_elevation_at(heightmap, x_m, y_m)
    assert np.isfinite(elevation)
    assert min(heightmap.values.ravel()) <= elevation <= max(heightmap.values.ravel())


def test_surface_projection_preserves_xy_and_uses_mesh_surface(simulation_case) -> None:
    x_m = -12.5
    y_m = 7.5
    projected = project_to_terrain_surface(
        simulation_case.heightmap, x_m, y_m, clearance_m=0.03
    )

    assert projected.x_m == x_m
    assert projected.y_m == y_m
    assert projected.z_m == pytest.approx(
        simulation_case.heightmap.surface_elevation_at(x_m, y_m) + 0.03
    )

    with pytest.raises(ValueError, match="non-negative"):
        project_to_terrain_surface(
            simulation_case.heightmap, x_m, y_m, clearance_m=-0.01
        )


def test_out_of_mesh_and_prohibited_cells_are_rejected(simulation_case) -> None:
    outside = StationaryMotion(kind="stationary", position=Position2D(x_m=49.0, y_m=49.0))
    with pytest.raises(TrajectoryValidationError, match="outside"):
        simulate(simulation_case, _config(simulation_case.case_spec.case_id, outside))

    values = np.full(simulation_case.heightmap.values.shape, TraversabilityValue.UNKNOWN)
    x_index, y_index = simulation_case.heightmap.indices_at(0.0, 0.0)
    values[y_index, x_index] = TraversabilityValue.PROHIBITED
    prohibited_case = replace(
        simulation_case,
        traversability=TraversabilityMap(
            values=values,
            grid=simulation_case.heightmap.grid,
            difficult_slope_deg=None,
        ),
        case_spec=simulation_case.case_spec.model_copy(
            update={
                "environment": simulation_case.case_spec.environment.model_copy(
                    update={"traversability": "traversability.tif"}
                )
            }
        ),
    )
    motion = StationaryMotion(kind="stationary", position=Position2D(x_m=0.0, y_m=0.0))
    with pytest.raises(TrajectoryValidationError, match="prohibited"):
        simulate(prohibited_case, _config(simulation_case.case_spec.case_id, motion))


def test_simulation_does_not_use_farm_boundary_as_physical_limit(simulation_case) -> None:
    motion = StationaryMotion(kind="stationary", position=Position2D(x_m=40.0, y_m=0.0))
    result = simulate(simulation_case, _config(simulation_case.case_spec.case_id, motion))
    assert result.frames[0].states[0].position.x_m == 40.0
