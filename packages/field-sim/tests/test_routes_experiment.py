from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import numpy as np
import pandas as pd
from field_environment import TraversabilityMap, TraversabilityValue, save_case

from field_sim import (
    RouteDefinition,
    WaypointSet,
    WaypointSpec,
    author_experiment,
    build_placement_definitions,
    build_route_definitions,
    generate_resolved_route,
    load_experiment_plan,
    load_resolved_route,
    run_experiment_plan,
    save_resolved_route,
    save_waypoint_set,
)
from field_sim.notebook import WaypointSetManager
from field_sim.route_planning import resolve_waypoint_position


def _waypoints(simulation_case) -> WaypointSet:
    return WaypointSet(
        waypoint_set_id="test-corridor-v1",
        case_id=simulation_case.case_spec.case_id,
        waypoints=(
            WaypointSpec(id="WP001", x_m=-20.0, y_m=-10.0),
            WaypointSpec(id="WP002", x_m=0.0, y_m=10.0),
            WaypointSpec(id="WP003", x_m=20.0, y_m=-10.0),
        ),
    )


def _case_with_prohibited_block(simulation_case):
    values = np.full(
        simulation_case.heightmap.values.shape,
        TraversabilityValue.TRAVERSABLE,
        dtype=np.uint8,
    )
    values[4:6, 4:6] = TraversabilityValue.PROHIBITED
    return replace(
        simulation_case,
        traversability=TraversabilityMap(
            values=values,
            grid=simulation_case.heightmap.grid,
            difficult_slope_deg=None,
        ),
    )


def test_direct_and_meandering_routes_are_distinct_and_reproducible(simulation_case):
    waypoint_set = _waypoints(simulation_case)
    direct_definition = RouteDefinition(
        route_id="direct-v1",
        route_group_id=waypoint_set.waypoint_set_id,
        method="direct",
        waypoint_set="waypoints.yaml",
        parameters={"point_spacing_m": 1.0},
    )
    meandering_definition = RouteDefinition(
        route_id="meandering-v1",
        route_group_id=waypoint_set.waypoint_set_id,
        method="meandering",
        waypoint_set="waypoints.yaml",
        seed=17,
        parameters={
            "point_spacing_m": 1.0,
            "max_lateral_offset_m": 2.0,
            "meander_interval_m": 10.0,
        },
    )

    direct = generate_resolved_route(simulation_case, direct_definition, waypoint_set)
    first = generate_resolved_route(
        simulation_case, meandering_definition, waypoint_set
    )
    second = generate_resolved_route(
        simulation_case, meandering_definition, waypoint_set
    )

    assert np.allclose(first.points[["x_m", "y_m"]], second.points[["x_m", "y_m"]])
    assert first.route_sha256 == second.route_sha256
    assert first.length_m > direct.length_m
    assert direct.points.iloc[0].x_m == waypoint_set.waypoints[0].x_m
    assert direct.points.iloc[-1].x_m == waypoint_set.waypoints[-1].x_m


def test_smooth_route_passes_every_waypoint_and_meandering_uses_same_endpoints(
    simulation_case,
):
    waypoint_set = _waypoints(simulation_case)
    smooth_definition = RouteDefinition(
        route_id="smooth-v1",
        route_group_id=waypoint_set.waypoint_set_id,
        method="smooth",
        waypoint_set="waypoints.yaml",
        parameters={"point_spacing_m": 1.0, "smoothing_tension": 0.0},
    )
    meandering_definition = RouteDefinition(
        route_id="smooth-meandering-v1",
        route_group_id=waypoint_set.waypoint_set_id,
        method="meandering",
        waypoint_set="waypoints.yaml",
        seed=23,
        parameters={
            "point_spacing_m": 1.0,
            "smoothing_tension": 0.0,
            "max_lateral_offset_m": 2.0,
            "meander_interval_m": 10.0,
        },
    )

    smooth = generate_resolved_route(
        simulation_case, smooth_definition, waypoint_set
    )
    meandering = generate_resolved_route(
        simulation_case, meandering_definition, waypoint_set
    )

    smooth_xy = smooth.points[["x_m", "y_m"]].to_numpy()
    for waypoint in waypoint_set.waypoints:
        distances = np.linalg.norm(
            smooth_xy - np.asarray((waypoint.x_m, waypoint.y_m)), axis=1
        )
        assert distances.min() < 1.0e-9
    assert np.allclose(
        meandering.points.iloc[0][["x_m", "y_m"]].to_numpy(dtype=float),
        smooth.points.iloc[0][["x_m", "y_m"]].to_numpy(dtype=float),
    )
    assert np.allclose(
        meandering.points.iloc[-1][["x_m", "y_m"]].to_numpy(dtype=float),
        smooth.points.iloc[-1][["x_m", "y_m"]].to_numpy(dtype=float),
    )


def test_waypoint_on_prohibited_cell_is_snapped(simulation_case):
    environment_case = _case_with_prohibited_block(simulation_case)

    adjustment = resolve_waypoint_position(
        environment_case,
        0.0,
        0.0,
        parameters={"snap_radius_m": 30.0, "obstacle_clearance_m": 0.0},
        waypoint_id="WP001",
    )

    assert adjustment.reason is not None
    x_index, y_index = environment_case.heightmap.indices_at(
        adjustment.resolved_x_m, adjustment.resolved_y_m
    )
    assert (
        environment_case.traversability.values[y_index, x_index]
        != TraversabilityValue.PROHIBITED
    )


def test_smooth_route_uses_astar_around_prohibited_cells(simulation_case):
    environment_case = _case_with_prohibited_block(simulation_case)
    waypoint_set = WaypointSet(
        waypoint_set_id="obstacle-corridor-v1",
        case_id=environment_case.case_spec.case_id,
        waypoints=(
            WaypointSpec(id="WP001", x_m=-30.0, y_m=0.0),
            WaypointSpec(id="WP002", x_m=30.0, y_m=0.0),
        ),
    )
    definition = RouteDefinition(
        route_id="obstacle-smooth-v1",
        route_group_id=waypoint_set.waypoint_set_id,
        method="smooth",
        waypoint_set="waypoints.yaml",
        parameters={
            "point_spacing_m": 1.0,
            "smoothing_tension": 0.0,
            "obstacle_clearance_m": 0.0,
        },
    )

    route = generate_resolved_route(environment_case, definition, waypoint_set)

    assert route.planning["used_astar_segments"] == [1]
    for point in route.points.itertuples():
        x_index, y_index = environment_case.heightmap.indices_at(point.x_m, point.y_m)
        assert (
            environment_case.traversability.values[y_index, x_index]
            != TraversabilityValue.PROHIBITED
        )


def test_resolved_route_saves_reproducible_artifacts(tmp_path, simulation_case):
    cases_root = tmp_path / "cases"
    save_case(simulation_case, cases_root)
    waypoint_set = _waypoints(simulation_case)
    definition = RouteDefinition(
        route_id="saved-direct-v1",
        route_group_id=waypoint_set.waypoint_set_id,
        method="direct",
        waypoint_set="waypoints.yaml",
        parameters={"point_spacing_m": 1.0},
    )
    route = generate_resolved_route(simulation_case, definition, waypoint_set)

    directory = save_resolved_route(cases_root, route)

    assert (directory / "route.json").is_file()
    assert (directory / "path.geojson").is_file()
    assert (directory / "path_points.parquet").is_file()
    assert (directory / "preview.png").is_file()
    loaded = load_resolved_route(
        cases_root, simulation_case.case_spec.case_id, definition.route_id
    )
    assert loaded.definition == route.definition
    assert loaded.waypoint_set == route.waypoint_set
    pd.testing.assert_frame_equal(loaded.points, route.points)


def test_experiment_plan_expands_cartesian_matrix(tmp_path: Path):
    experiment = tmp_path / "experiment"
    (experiment / "placements").mkdir(parents=True)
    (experiment / "routes").mkdir()
    for name in ("grid.yaml", "uniform.yaml"):
        (experiment / "placements" / name).write_text("layout_id: unused\n", encoding="utf-8")
    for name in ("direct.yaml", "meandering.yaml"):
        (experiment / "routes" / name).write_text("route_id: unused\n", encoding="utf-8")
    plan_path = experiment / "experiment.yaml"
    plan_path.write_text(
        """
experiment_id: experiment-v1
case_id: case-v1
placements: [placements/grid.yaml, placements/uniform.yaml]
routes: [routes/direct.yaml, routes/meandering.yaml]
seeds: [1, 2]
matrix: {mode: cartesian}
""",
        encoding="utf-8",
    )

    loaded = load_experiment_plan(plan_path)

    assert len(loaded.combinations) == 8
    assert loaded.dataframe().combination_id.is_unique


def test_python_authoring_generates_commented_yaml_and_cartesian_plan(tmp_path):
    waypoint_set = WaypointSet(
        waypoint_set_id="authoring-corridor-v1",
        case_id="authoring-case-v1",
        waypoints=(
            WaypointSpec(id="WP001", x_m=0.0, y_m=0.0),
            WaypointSpec(id="WP002", x_m=20.0, y_m=0.0),
        ),
    )

    authored = author_experiment(
        tmp_path,
        experiment_id="authoring-experiment-v1",
        case_id=waypoint_set.case_id,
        camera_placements=(("grid", 40.0), ("uniform", 100)),
        camera_counts=(3, 6),
        waypoint_set=waypoint_set,
        route_methods=("direct", "meandering"),
        seeds=(1, 2),
    )

    assert len(authored.placement_definitions) == 4
    assert len(authored.route_definitions) == 2
    assert len(authored.loaded_plan.combinations) == 16
    plan_text = authored.plan_path.read_text(encoding="utf-8")
    grid_text = (
        authored.directory / "placements/grid-40m-cam3-v1.yaml"
    ).read_text(encoding="utf-8")
    assert "# 使用する農場Case" in plan_text
    assert "spacing_m: 40.0  # 格子の間隔m" in grid_text
    assert "point_count: 100" in (
        authored.directory / "placements/uniform-100points-cam3-v1.yaml"
    ).read_text(encoding="utf-8")


def test_python_authoring_expands_three_waypoint_sets_to_six_routes(tmp_path):
    waypoint_sets = tuple(
        WaypointSet(
            waypoint_set_id=f"corridor-{index:03d}-v1",
            case_id="multi-route-case-v1",
            waypoints=(
                WaypointSpec(id="WP001", x_m=0.0, y_m=float(index)),
                WaypointSpec(id="WP002", x_m=20.0, y_m=float(index)),
            ),
        )
        for index in range(1, 4)
    )

    authored = author_experiment(
        tmp_path,
        experiment_id="multi-route-experiment-v1",
        case_id="multi-route-case-v1",
        camera_placements=(("grid", 40.0), ("uniform", 100)),
        camera_counts=(6,),
        waypoint_sets=waypoint_sets,
        route_methods=("smooth", "meandering"),
        seeds=(42,),
    )

    assert len(authored.waypoint_sets) == 3
    assert len(authored.route_definitions) == 6
    assert len(authored.loaded_plan.combinations) == 12
    assert len(list((authored.directory / "waypoint_sets").glob("*.yaml"))) == 3
    assert len(list((authored.directory / "routes").glob("*.yaml"))) == 6


def test_waypoint_set_manager_loads_three_saved_sets(tmp_path, simulation_case):
    waypoint_directory = tmp_path / "waypoint_sets"
    for index in range(1, 4):
        waypoint_set = WaypointSet(
            waypoint_set_id=f"gui-route-{index:03d}-v1",
            case_id=simulation_case.case_spec.case_id,
            waypoints=(
                WaypointSpec(id="WP001", x_m=-20.0, y_m=float(index)),
                WaypointSpec(id="WP002", x_m=20.0, y_m=float(index)),
            ),
        )
        save_waypoint_set(waypoint_directory / f"{waypoint_set.waypoint_set_id}.yaml", waypoint_set)

    manager = WaypointSetManager(
        simulation_case,
        storage_directory=waypoint_directory,
        required_count=3,
        route_methods=("smooth", "meandering"),
    )

    assert [item.waypoint_set_id for item in manager.get_waypoint_sets()] == [
        "gui-route-001-v1",
        "gui-route-002-v1",
        "gui-route-003-v1",
    ]


def test_custom_methods_resolve_workspace_modules():
    waypoint_set = WaypointSet(
        waypoint_set_id="custom-corridor-v1",
        case_id="custom-case-v1",
        waypoints=(
            WaypointSpec(id="WP001", x_m=0.0, y_m=0.0),
            WaypointSpec(id="WP002", x_m=1.0, y_m=1.0),
        ),
    )

    placement = build_placement_definitions(
        (("ridge_priority", 50),), (6,)
    )[0]
    route = build_route_definitions(("forest_edge",), waypoint_set)[0]

    assert placement.module == "workspace.placement.ridge_priority"
    assert placement.parameters == {"value": 50}
    assert route.module == "workspace.behavior.routes.forest_edge"


def test_experiment_batch_shares_ground_truth_between_layouts(
    tmp_path: Path, simulation_case
):
    cases_root = tmp_path / "cases"
    save_case(simulation_case, cases_root)
    experiment = tmp_path / "experiment"
    (experiment / "placements").mkdir(parents=True)
    (experiment / "routes").mkdir()
    (experiment / "waypoint_sets").mkdir()
    (experiment / "placements/grid.yaml").write_text(
        """
layout_id: batch-grid-v1
method: grid
mount: {camera_count: 3}
parameters: {spacing_m: 20}
""",
        encoding="utf-8",
    )
    (experiment / "placements/uniform.yaml").write_text(
        """
layout_id: batch-uniform-v1
method: uniform
mount: {camera_count: 3}
parameters: {point_count: match_grid40, reference_grid_spacing_m: 20}
""",
        encoding="utf-8",
    )
    (experiment / "waypoint_sets/corridor.yaml").write_text(
        f"""
waypoint_set_id: batch-corridor-v1
case_id: {simulation_case.case_spec.case_id}
waypoints:
  - {{id: WP001, x_m: -20, y_m: -10}}
  - {{id: WP002, x_m: 20, y_m: 10}}
""",
        encoding="utf-8",
    )
    (experiment / "routes/direct.yaml").write_text(
        """
route_id: batch-direct-v1
route_group_id: batch-corridor-v1
method: direct
waypoint_set: ../waypoint_sets/corridor.yaml
parameters: {point_spacing_m: 5}
""",
        encoding="utf-8",
    )
    plan_path = experiment / "experiment.yaml"
    plan_path.write_text(
        f"""
experiment_id: batch-experiment-v1
case_id: {simulation_case.case_spec.case_id}
placements: [placements/grid.yaml, placements/uniform.yaml]
routes: [routes/direct.yaml]
seeds: [9]
simulation: {{speed_mps: 10, step_s: 1}}
""",
        encoding="utf-8",
    )

    result = run_experiment_plan(cases_root, load_experiment_plan(plan_path))

    assert set(result.statuses.values()) == {"completed"}
    dataset = cases_root / simulation_case.case_spec.case_id / "datasets/batch-direct-v1-seed9"
    assert (dataset / "ground_truth.parquet").is_file()
    assert (dataset / "observations/batch-grid-v1/observations.parquet").is_file()
    assert (dataset / "observations/batch-uniform-v1/observations.parquet").is_file()
    assert len(list(dataset.glob("ground_truth*.parquet"))) == 1
