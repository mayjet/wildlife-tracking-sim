from __future__ import annotations

import numpy as np
import pandas as pd

from field_sim import (
    HerdProfile,
    HerdSimulationConfig,
    ResolvedRoute,
    RouteDefinition,
    WaypointSet,
    WaypointSpec,
    simulate_herd,
)


def _route(case_id: str) -> ResolvedRoute:
    waypoint_set = WaypointSet(
        waypoint_set_id="herd-corridor",
        case_id=case_id,
        waypoints=(
            WaypointSpec(id="start", x_m=-20.0, y_m=0.0),
            WaypointSpec(id="end", x_m=20.0, y_m=0.0),
        ),
    )
    points = pd.DataFrame(
        {
            "point_index": [0, 1, 2, 3, 4],
            "waypoint_segment_index": [0, 0, 0, 0, 0],
            "distance_m": [0.0, 10.0, 20.0, 30.0, 40.0],
            "x_m": [-20.0, -10.0, 0.0, 10.0, 20.0],
            "y_m": [0.0, 0.0, 0.0, 0.0, 0.0],
            "z_m": [0.0, 0.0, 0.0, 0.0, 0.0],
            "heading_rad": [0.0, 0.0, 0.0, 0.0, 0.0],
            "terrain_slope_deg": [0.0, 0.0, 0.0, 0.0, 0.0],
        }
    )
    return ResolvedRoute(
        definition=RouteDefinition(
            route_id="herd-route",
            route_group_id="herd-group",
            method="direct",
            waypoint_set="unused.yaml",
        ),
        waypoint_set=waypoint_set,
        points=points,
    )


def _config(case_id: str) -> HerdSimulationConfig:
    return HerdSimulationConfig(
        case_id=case_id,
        dataset_id="herd-dataset",
        route_id="herd-route",
        herd_id="herd-001",
        seed=7,
        step_s=1.0,
        speed_mps=2.0,
        profile=HerdProfile(
            profile_id="small",
            deer_count=5,
            adult_count=3,
            juvenile_count=2,
            group_radius_m=8.0,
            minimum_separation_m=1.5,
            follower_delay_s=0.0,
        ),
    )


def test_herd_is_reproducible_and_uses_contract_ground_truth(simulation_case) -> None:
    route = _route(simulation_case.case_spec.case_id)
    first = simulate_herd(simulation_case, route, _config(route.waypoint_set.case_id))
    second = simulate_herd(simulation_case, route, _config(route.waypoint_set.case_id))

    assert first.frames == second.frames
    assert all(len(frame.states) == 5 for frame in first.frames)
    assert all(state.group_truth_id == "herd-001" for state in first.frames[0].states)
    assert sum(state.is_group_leader for state in first.frames[0].states) == 1
    for frame in first.frames:
        positions = np.asarray(
            [(state.position.x_m, state.position.y_m) for state in frame.states]
        )
        separations = [
            float(np.linalg.norm(positions[first_index] - positions[second_index]))
            for first_index in range(len(positions))
            for second_index in range(first_index)
        ]
        assert min(separations) >= 1.5 - 1.0e-6
        leader = next(state for state in frame.states if state.is_group_leader)
        leader_xy = np.asarray((leader.position.x_m, leader.position.y_m))
        assert max(
            float(np.linalg.norm(position - leader_xy)) for position in positions
        ) <= 8.0 + 1.0e-6
        for state in frame.states:
            assert not simulation_case.buildings or not simulation_case.buildings.covers(
                state.position.x_m, state.position.y_m
            )
            assert state.position.z_m == simulation_case.heightmap.surface_elevation_at(
                state.position.x_m, state.position.y_m
            )
    leader_positions = [
        next(state for state in frame.states if state.is_group_leader).position
        for frame in first.frames
    ]
    assert leader_positions[0].x_m == -20.0
    assert leader_positions[-1].x_m == 20.0
