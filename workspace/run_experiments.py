#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path
import subprocess
import sys
import time
from typing import Any

import pandas as pd

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
for source_root in (
    REPOSITORY_ROOT / "libs" / "shepherd-contracts" / "src",
    REPOSITORY_ROOT / "packages" / "field-environment" / "src",
    REPOSITORY_ROOT / "packages" / "field-campost" / "src",
    REPOSITORY_ROOT / "packages" / "field-sim" / "src",
    REPOSITORY_ROOT / "packages" / "field-tracker" / "src",
    REPOSITORY_ROOT / "packages" / "field-benchmark" / "src",
    REPOSITORY_ROOT / "packages" / "field-visualizer" / "src",
):
    source_text = str(source_root)
    if source_text not in sys.path:
        sys.path.insert(0, source_text)

from field_benchmark import (
    BenchmarkExecutionJournal,
    ExecutionCondition,
    ExecutionStatus,
    discover_benchmark_conditions,
    evaluate_saved_group_run,
    evaluate_saved_run,
)
from field_campost import (
    GenesisExperimentRuntime,
    GenesisMeshSource,
    GenesisViewerOptions,
    build_genesis_deer_frame,
    build_genesis_mesh_scene,
    draw_genesis_experiment_overlays,
    genesis_deer_actor_specs,
    interpolate_genesis_deer_frames,
    load_placement_definition,
    load_observation_point_layout,
    write_genesis_mesh_assets,
    write_observation_infrastructure_assets,
)
from field_environment import find_repository_root, load_case, resolve_case_path
from field_sim import load_simulation_dataset
from field_sim import load_experiment_plan, load_route_definition, run_experiment_plan
from field_tracker import (
    create_tracker,
    load_observation_frames,
    run_tracker_stream,
    save_tracking_run,
)
from field_visualizer import RerunLiveSession


DEFAULT_TRACKER_SETTINGS: dict[str, Any] = {
    "confirmation_hits": 3,
    "confirmation_window": 5,
    "association_gate_m": 8.0,
    "ambiguity_margin_m": 1.5,
    "lost_after_misses": 1,
    "retire_after_s": 180.0,
    "exit_confirmation_s": 5.0,
    "group_distance_m": 20.0,
    "group_leave_distance_m": 25.0,
    "group_confirmation_s": 3.0,
    "group_leave_confirmation_s": 3.0,
}


def _metrics(path: Path) -> dict[str, object]:
    return json.loads(path.read_text(encoding="utf-8"))


def _visibility_coverage(case_directory: Path, layout_id: str) -> float | None:
    for path in (
        case_directory / "visibility_maps" / layout_id / "coverage-metrics-1m-binary.json",
        case_directory / "visibility_maps" / layout_id / "coverage_metrics.json",
    ):
        if path.is_file():
            return _metrics(path).get("class_rates", {}).get("fully_visible")
    return None


def _write_summary(
    case_directory: Path,
    benchmark_id: str,
    conditions: tuple[ExecutionCondition, ...],
    tracker_seed: int,
) -> None:
    rows = []
    for condition in conditions:
        path = case_directory / "runs" / condition.run_id / "group_benchmark_metrics.json"
        if not path.is_file():
            continue
        rows.append(
            {
                "case_id": case_directory.name,
                "benchmark_id": benchmark_id,
                "dataset_id": condition.dataset_id,
                "layout_id": condition.layout_id,
                "tracker_method": condition.tracker_method,
                "tracker_seed": tracker_seed,
                "visibility_coverage_rate": _visibility_coverage(
                    case_directory, condition.layout_id
                ),
                "run_id": condition.run_id,
                **_metrics(path),
            }
        )
    destination = case_directory / "benchmarks" / benchmark_id
    table = pd.DataFrame(rows)
    table.to_parquet(destination / "condition_results.parquet", index=False, engine="pyarrow")
    table.to_csv(destination / "summary.csv", index=False)


def _write_live_execution(
    run_directory: Path,
    dataset,
    arguments: argparse.Namespace,
    display_warnings: list[str],
    *,
    resumed_from_tracking: bool = False,
) -> None:
    (run_directory / "live_execution.json").write_text(
        json.dumps(
            {
                "schema_version": "1.0",
                "simulation_step_s": dataset.manifest.simulation_step_s,
                "simulation_speed": arguments.simulation_speed,
                "rerun_recording": (
                    "recording.rrd"
                    if (run_directory / "recording.rrd").is_file()
                    else None
                ),
                "genesis_enabled": arguments.genesis,
                "genesis_viewer": arguments.genesis_viewer,
                "genesis_fov": arguments.genesis_fov,
                "ground_truth_supplied_to_tracker": False,
                "resumed_from_saved_tracking": resumed_from_tracking,
                "display_warnings": display_warnings,
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )


def _genesis_runtime(
    environment_case,
    first_frame,
    layout,
    cache: Path,
    backend: str,
    *,
    show_fov: bool,
    show_viewer: bool,
):
    assets = write_genesis_mesh_assets(environment_case, cache)
    sources = [GenesisMeshSource("terrain", assets.terrain, (0.55, 0.45, 0.30))]
    for name, path, color in (
        ("forest", assets.forest, (0.05, 0.28, 0.08)),
        ("buildings", assets.buildings, (0.75, 0.35, 0.10)),
        ("facility-buildings", assets.facility_buildings, (0.95, 0.55, 0.10)),
    ):
        if path is not None:
            sources.append(GenesisMeshSource(name, path, color))
    infrastructure = write_observation_infrastructure_assets(layout, cache / layout.layout_id)
    sources.extend(
        (
            GenesisMeshSource("observation-poles", infrastructure.poles, (0.18, 0.18, 0.20)),
            GenesisMeshSource("camera-housings", infrastructure.camera_housings, (0.05, 0.18, 0.30)),
        )
    )
    bounds = environment_case.heightmap.bounds
    center_x = (bounds.min_x_m + bounds.max_x_m) / 2.0
    center_y = (bounds.min_y_m + bounds.max_y_m) / 2.0
    center_z = float(environment_case.heightmap.values.mean())
    extent = max(bounds.max_x_m - bounds.min_x_m, bounds.max_y_m - bounds.min_y_m)
    options = GenesisViewerOptions(
        camera_position=(center_x - extent * 0.6, center_y - extent * 0.6, center_z + extent * 0.65),
        camera_look_at=(center_x, center_y, center_z),
        world_frame_size_m=max(10.0, extent * 0.1),
        refresh_rate_hz=10,
    )
    deer_frame = build_genesis_deer_frame(environment_case, first_frame)
    scene = build_genesis_mesh_scene(
        tuple(sources),
        backend=backend,
        show_viewer=show_viewer,
        viewer_options=options,
        actors=genesis_deer_actor_specs(deer_frame),
    )
    if show_fov:
        draw_genesis_experiment_overlays(scene, layout, show_fov=True)
    truth_ids = tuple(proxy.truth_id for proxy in deer_frame.proxies)
    return GenesisExperimentRuntime(scene, truth_ids)


def _replay_genesis(
    environment_case,
    dataset,
    layout,
    arguments: argparse.Namespace,
    case_id: str,
) -> None:
    runtime = _genesis_runtime(
        environment_case,
        dataset.frames[0],
        layout,
        Path(arguments.mesh_cache) / case_id,
        arguments.genesis_backend,
        show_fov=arguments.genesis_fov,
        show_viewer=True,
    )
    previous = build_genesis_deer_frame(environment_case, dataset.frames[0])
    runtime.update(previous)
    for truth in dataset.frames[1:]:
        current = build_genesis_deer_frame(environment_case, truth)
        duration_s = max(current.timestamp_s - previous.timestamp_s, 0.0)
        substeps = max(1, int(duration_s * 10.0))
        for substep in range(1, substeps + 1):
            time.sleep(duration_s / substeps / arguments.simulation_speed)
            runtime.update(
                interpolate_genesis_deer_frames(previous, current, substep / substeps)
            )
        previous = current


def _run(arguments: argparse.Namespace) -> int:
    root = find_repository_root(Path.cwd())
    cases_root = (root / arguments.cases_root).resolve()
    loaded_plan = load_experiment_plan(arguments.plan, start=root)
    if arguments.tracker_seed is None:
        arguments.tracker_seed = loaded_plan.plan.tracker_seed
    case_id = loaded_plan.plan.case_id
    if arguments.case_id is not None and arguments.case_id != case_id:
        raise ValueError("--case-id does not match the saved experiment plan")
    case_directory = resolve_case_path(cases_root, case_id)
    environment_case = load_case(cases_root, case_id)
    methods = tuple(
        dict.fromkeys(arguments.tracker_method or loaded_plan.plan.tracker_methods)
    )
    journal_configuration = {
        "plan": loaded_plan.plan.model_dump(mode="json"),
        "tracker_methods": list(methods),
        "tracker_seed": arguments.tracker_seed,
    }
    journal = BenchmarkExecutionJournal(
        cases_root,
        case_id=case_id,
        benchmark_id=arguments.benchmark_id,
        conditions=(),
        configuration=journal_configuration,
    )

    print(f"Dataset/Observation生成: {loaded_plan.path}")
    generation = run_experiment_plan(cases_root, loaded_plan, overwrite=False)
    journal.record_generation(generation.statuses)
    generation_failures = {
        condition_id: status
        for condition_id, status in generation.statuses.items()
        if status != "completed"
    }
    if generation_failures:
        details = "; ".join(
            f"{condition_id}: {status}"
            for condition_id, status in sorted(generation_failures.items())
        )
        raise RuntimeError(f"Dataset/Observation generation failed: {details}")

    planned_dataset_ids = {
        _dataset_id_for_combination(loaded_plan, combination)
        for combination in loaded_plan.combinations
    }
    planned_layout_ids = {
        _layout_id_for_combination(combination)
        for combination in loaded_plan.combinations
    }
    discovered = tuple(
        condition
        for condition in discover_benchmark_conditions(cases_root, case_id)
        if condition[0] in planned_dataset_ids and condition[1] in planned_layout_ids
    )
    if arguments.dataset_id:
        discovered = tuple(item for item in discovered if item[0] in arguments.dataset_id)
    if arguments.layout_id:
        discovered = tuple(item for item in discovered if item[1] in arguments.layout_id)
    conditions = tuple(
        ExecutionCondition(dataset_id, layout_id, method, arguments.benchmark_id)
        for dataset_id, layout_id in discovered
        for method in methods
    )
    if not conditions:
        raise ValueError("実行対象となるDataset・配置・Trackerがない")
    journal = BenchmarkExecutionJournal(
        cases_root,
        case_id=case_id,
        benchmark_id=arguments.benchmark_id,
        conditions=conditions,
        configuration=journal_configuration,
    )
    farm_coordinates = tuple(
        (float(x_m), float(y_m))
        for x_m, y_m in environment_case.farm_boundary.polygon.exterior.coords
    )
    failures = 0
    for index, condition in enumerate(conditions, start=1):
        existing_run = case_directory / "runs" / condition.run_id
        expected_outputs = [
            existing_run / "run_manifest.json",
            existing_run / "group_benchmark_metrics.json",
        ]
        if (
            journal.status(condition) is ExecutionStatus.COMPLETED
            and all(path.is_file() for path in expected_outputs)
        ):
            if arguments.genesis_viewer:
                dataset = load_simulation_dataset(
                    cases_root, case_id, condition.dataset_id
                )
                layout = load_observation_point_layout(
                    cases_root, case_id, condition.layout_id
                )
                _replay_genesis(environment_case, dataset, layout, arguments, case_id)
            print(f"[{index}/{len(conditions)}] SKIP {condition.condition_id}")
            continue
        print(f"[{index}/{len(conditions)}] RUN  {condition.condition_id}")
        journal.mark_running(condition)
        rerun_session = None
        recording_temporary = None
        display_warnings: list[str] = []
        try:
            dataset = load_simulation_dataset(cases_root, case_id, condition.dataset_id)
            observation_path = (
                dataset.directory / "observations" / condition.layout_id / "observations.parquet"
            )
            observation_frames = load_observation_frames(observation_path)
            truth_by_time = {frame.timestamp_s: frame for frame in dataset.frames}
            layout = load_observation_point_layout(
                cases_root, case_id, condition.layout_id
            )
            run_directory = case_directory / "runs" / condition.run_id
            if run_directory.exists():
                required = (
                    run_directory / "run_manifest.json",
                    run_directory / "group_benchmark_metrics.json",
                )
                if all(path.is_file() for path in required):
                    print(f"既存Runを再利用: {run_directory}")
                    if arguments.genesis_viewer:
                        _replay_genesis(environment_case, dataset, layout, arguments, case_id)
                    journal.mark_completed(condition)
                    continue
                tracking_outputs = (
                    run_directory / "run_manifest.json",
                    run_directory / "tracking.parquet",
                    run_directory / "group_tracking.parquet",
                )
                if all(path.is_file() for path in tracking_outputs):
                    evaluate_saved_run(
                        cases_root, case_id, condition.dataset_id, condition.run_id
                    )
                    evaluate_saved_group_run(
                        cases_root,
                        case_id,
                        condition.dataset_id,
                        condition.run_id,
                        observation_source=observation_path,
                    )
                    display_warnings.append(
                        "Tracker output was reused after an interrupted evaluation"
                    )
                    _write_live_execution(
                        run_directory,
                        dataset,
                        arguments,
                        display_warnings,
                        resumed_from_tracking=True,
                    )
                    journal.mark_completed(condition)
                    continue
                raise FileExistsError(f"Incomplete Run already exists: {run_directory}")
            if arguments.rerun:
                recording_directory = (
                    case_directory / "benchmarks" / arguments.benchmark_id / ".recordings"
                )
                recording_directory.mkdir(parents=True, exist_ok=True)
                recording_temporary = recording_directory / f"{condition.run_id}.rrd"
                recording_temporary.unlink(missing_ok=True)
                try:
                    rerun_session = RerunLiveSession(
                        run_id=condition.run_id,
                        recording_path=recording_temporary,
                        grpc_url=arguments.rerun_url,
                    )
                    rerun_session.log_environment(environment_case, layout)
                except Exception as error:
                    display_warnings.append(
                        f"Rerun initialization failed: {type(error).__name__}: {error}"
                    )
                    rerun_session = None
            genesis_runtime = None
            if arguments.genesis:
                try:
                    genesis_runtime = _genesis_runtime(
                        environment_case,
                        dataset.frames[0],
                        layout,
                        Path(arguments.mesh_cache) / case_id,
                        arguments.genesis_backend,
                        show_fov=arguments.genesis_fov,
                        show_viewer=arguments.genesis_viewer,
                    )
                except Exception as error:
                    display_warnings.append(
                        f"Genesis initialization failed: {type(error).__name__}: {error}"
                    )
            config = {
                **DEFAULT_TRACKER_SETTINGS,
                "tracker_id": condition.tracker_method,
                "farm_boundary": farm_coordinates,
            }
            previous_wall_time = time.monotonic()
            previous_simulation_time = observation_frames[0].timestamp_s
            previous_deer_frame = None

            def on_frame(observation_frame, tracking_frame):
                nonlocal previous_wall_time, previous_simulation_time, previous_deer_frame
                truth = truth_by_time.get(observation_frame.timestamp_s)
                if rerun_session is not None:
                    try:
                        rerun_session.log_frame(
                            timestamp_s=observation_frame.timestamp_s,
                            ground_truth=truth,
                            observations=observation_frame,
                            tracking=tracking_frame,
                        )
                    except Exception as error:
                        display_warnings.append(
                            f"Rerun frame failed: {type(error).__name__}: {error}"
                        )
                if genesis_runtime is not None and truth is not None:
                    try:
                        current_deer_frame = build_genesis_deer_frame(environment_case, truth)
                        if previous_deer_frame is None:
                            genesis_runtime.update(current_deer_frame)
                        elif not arguments.genesis_viewer:
                            genesis_runtime.update(current_deer_frame)
                        else:
                            duration_s = max(
                                current_deer_frame.timestamp_s - previous_deer_frame.timestamp_s,
                                0.0,
                            )
                            substeps = max(1, int(duration_s * 10.0))
                            for substep in range(1, substeps + 1):
                                target_delay = duration_s / substeps / arguments.simulation_speed
                                elapsed = time.monotonic() - previous_wall_time
                                if target_delay > elapsed:
                                    time.sleep(target_delay - elapsed)
                                genesis_runtime.update(
                                    interpolate_genesis_deer_frames(
                                        previous_deer_frame,
                                        current_deer_frame,
                                        substep / substeps,
                                    )
                                )
                                previous_wall_time = time.monotonic()
                        previous_deer_frame = current_deer_frame
                        previous_simulation_time = observation_frame.timestamp_s
                    except Exception as error:
                        display_warnings.append(
                            f"Genesis frame failed: {type(error).__name__}: {error}"
                        )

            result = run_tracker_stream(
                create_tracker(condition.tracker_method),
                observation_frames,
                config,
                arguments.tracker_seed,
                on_frame=on_frame,
            )
            if rerun_session is not None:
                rerun_session.close()
                display_warnings.extend(rerun_session.warnings)
                rerun_session = None
            save_tracking_run(
                cases_root,
                case_id=case_id,
                dataset_id=condition.dataset_id,
                run_id=condition.run_id,
                seed=arguments.tracker_seed,
                tracker_config=config,
                result=result,
                observation_ref=str(observation_path.relative_to(case_directory)),
                overwrite=False,
            )
            if recording_temporary is not None and recording_temporary.is_file():
                recording_temporary.replace(run_directory / "recording.rrd")
            evaluate_saved_run(
                cases_root, case_id, condition.dataset_id, condition.run_id
            )
            evaluate_saved_group_run(
                cases_root,
                case_id,
                condition.dataset_id,
                condition.run_id,
                observation_source=observation_path,
            )
            _write_live_execution(
                run_directory, dataset, arguments, display_warnings
            )
            journal.mark_completed(condition)
        except Exception as error:
            failures += 1
            if rerun_session is not None:
                rerun_session.close()
            journal.mark_failed(condition, error)
            print(f"FAILED: {condition.condition_id}: {type(error).__name__}: {error}")
            if arguments.fail_fast:
                raise
    _write_summary(case_directory, arguments.benchmark_id, conditions, arguments.tracker_seed)
    print(f"Benchmark: {case_directory / 'benchmarks' / arguments.benchmark_id}")
    return 1 if failures else 0


def _dataset_id_for_combination(loaded_plan, combination) -> str:
    route, _ = load_route_definition(combination.route_definition_path)
    profile_id = combination.herd_profile_id
    return (
        f"{route.route_id}-"
        f"{profile_id + '-' if profile_id is not None else ''}seed{combination.seed}"
    )


def _layout_id_for_combination(combination) -> str:
    definition, _ = load_placement_definition(combination.layout_definition_path)
    return definition.layout_id


def _serve(arguments: argparse.Namespace) -> int:
    command = [
        "rerun", "--serve-web", "--port", str(arguments.grpc_port),
        "--web-viewer-port", str(arguments.web_port),
    ]
    return subprocess.call(command)


def _replay(arguments: argparse.Namespace) -> int:
    root = find_repository_root(Path.cwd())
    cases_root = (root / arguments.cases_root).resolve()
    environment_case = load_case(cases_root, arguments.case_id)
    dataset = load_simulation_dataset(cases_root, arguments.case_id, arguments.dataset_id)
    layout = load_observation_point_layout(
        cases_root, arguments.case_id, arguments.layout_id
    )
    _replay_genesis(
        environment_case, dataset, layout, arguments, arguments.case_id
    )
    return 0


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="群れ追跡実験を一括実行・再開する")
    subparsers = parser.add_subparsers(dest="command", required=True)
    run = subparsers.add_parser("run", help="実験を実行する")
    run.add_argument("--plan", type=Path, required=True)
    run.add_argument("--case-id")
    run.add_argument("--benchmark-id", required=True)
    run.add_argument("--cases-root", type=Path, default=Path("cases"))
    run.add_argument("--dataset-id", action="append", default=[])
    run.add_argument("--layout-id", action="append", default=[])
    run.add_argument(
        "--tracker-method", action="append"
    )
    run.add_argument("--tracker-seed", type=int)
    run.add_argument("--simulation-speed", type=float, default=10.0)
    run.add_argument("--rerun", action=argparse.BooleanOptionalAction, default=True)
    run.add_argument("--rerun-url")
    run.add_argument("--genesis", action=argparse.BooleanOptionalAction, default=True)
    run.add_argument("--genesis-viewer", action="store_true")
    run.add_argument("--genesis-fov", action="store_true")
    run.add_argument("--genesis-backend", choices=("cpu", "gpu", "cuda"), default="cpu")
    run.add_argument("--mesh-cache", type=Path, default=Path("/tmp/shepherd-genesis"))
    run.add_argument("--fail-fast", action="store_true")
    run.set_defaults(handler=_run)
    serve = subparsers.add_parser("serve-rerun", help="Rerun Web Viewerを起動する")
    serve.add_argument("--grpc-port", type=int, default=9876)
    serve.add_argument("--web-port", type=int, default=9090)
    serve.set_defaults(handler=_serve)
    replay = subparsers.add_parser(
        "replay-genesis", help="保存済みGround TruthをGenesisで再生する"
    )
    replay.add_argument("--case-id", required=True)
    replay.add_argument("--dataset-id", required=True)
    replay.add_argument("--layout-id", required=True)
    replay.add_argument("--cases-root", type=Path, default=Path("cases"))
    replay.add_argument("--simulation-speed", type=float, default=10.0)
    replay.add_argument("--genesis-fov", action="store_true")
    replay.add_argument(
        "--genesis-backend", choices=("cpu", "gpu", "cuda"), default="cpu"
    )
    replay.add_argument("--mesh-cache", type=Path, default=Path("/tmp/shepherd-genesis"))
    replay.set_defaults(handler=_replay)
    return parser


def main() -> int:
    arguments = _parser().parse_args()
    if getattr(arguments, "simulation_speed", 1.0) <= 0.0:
        raise ValueError("simulation_speed must be positive")
    return int(arguments.handler(arguments))


if __name__ == "__main__":
    raise SystemExit(main())
