from __future__ import annotations

import json
from pathlib import Path

from field_environment import save_case
from workspace.run_experiments import main


def test_runner_executes_one_condition_from_saved_plan(
    tmp_path: Path, simulation_case, monkeypatch
) -> None:
    cases_root = tmp_path / "cases"
    save_case(simulation_case, cases_root)
    experiment = tmp_path / "experiment"
    (experiment / "placements").mkdir(parents=True)
    (experiment / "routes").mkdir()
    (experiment / "waypoint_sets").mkdir()
    (experiment / "placements/grid.yaml").write_text(
        """
layout_id: smoke-grid-v1
method: grid
mount: {camera_count: 3}
parameters: {spacing_m: 20}
""",
        encoding="utf-8",
    )
    (experiment / "waypoint_sets/corridor.yaml").write_text(
        f"""
waypoint_set_id: smoke-corridor-v1
case_id: {simulation_case.case_spec.case_id}
waypoints:
  - {{id: WP001, x_m: -15, y_m: -5}}
  - {{id: WP002, x_m: 15, y_m: 5}}
""",
        encoding="utf-8",
    )
    (experiment / "routes/direct.yaml").write_text(
        """
route_id: smoke-direct-v1
route_group_id: smoke-corridor-v1
method: direct
waypoint_set: ../waypoint_sets/corridor.yaml
parameters: {point_spacing_m: 5}
""",
        encoding="utf-8",
    )
    plan_path = experiment / "experiment.yaml"
    plan_path.write_text(
        f"""
experiment_id: runner-smoke-v1
case_id: {simulation_case.case_spec.case_id}
placements: [placements/grid.yaml]
routes: [routes/direct.yaml]
seeds: [7]
simulation: {{speed_mps: 10, step_s: 1}}
include_single_individual: false
herd_profiles:
  - profile_id: smoke-herd
    deer_count: 2
    adult_count: 1
    juvenile_count: 1
    group_radius_m: 5
    minimum_separation_m: 1
tracker_methods: [last_observation]
tracker_seed: 11
""",
        encoding="utf-8",
    )
    monkeypatch.setattr(
        "sys.argv",
        [
            "run_experiments.py",
            "run",
            "--plan",
            str(plan_path),
            "--benchmark-id",
            "runner-smoke-benchmark-v1",
            "--cases-root",
            str(cases_root),
            "--no-genesis",
            "--no-rerun",
        ],
    )

    assert main() == 0

    case_directory = cases_root / simulation_case.case_spec.case_id
    dataset = case_directory / "datasets/smoke-direct-v1-smoke-herd-seed7"
    assert (dataset / "ground_truth.parquet").is_file()
    assert (dataset / "observations/smoke-grid-v1/observations.parquet").is_file()
    dataset_manifest = json.loads((dataset / "manifest.json").read_text(encoding="utf-8"))
    assert "smoke-grid-v1" in dataset_manifest["scenario_config"]["observation_data_refs"]
    benchmark = case_directory / "benchmarks/runner-smoke-benchmark-v1"
    assert (benchmark / "condition_results.parquet").is_file()
    execution = json.loads(
        (benchmark / "execution_manifest.json").read_text(encoding="utf-8")
    )
    assert {item["status"] for item in execution["conditions"].values()} == {
        "COMPLETED"
    }
    run_id = next(iter(execution["conditions"].values()))["run_id"]
    run_directory = case_directory / "runs" / run_id
    assert (run_directory / "tracking.parquet").is_file()
    assert (run_directory / "group_tracking.parquet").is_file()
    assert (run_directory / "group_truth.parquet").is_file()
    assert (run_directory / "group_benchmark_assignments.parquet").is_file()
    assert (run_directory / "live_execution.json").is_file()

    assert main() == 0
