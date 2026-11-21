from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import asdict, dataclass
import json
from pathlib import Path
import shutil
from uuid import uuid4

import pandas as pd
from shepherd_contracts import JsonValue

from field_environment import load_case, resolve_case_path, validate_case_id
from field_tracker import (
    create_tracker,
    load_observation_frames,
    run_tracker,
    save_tracking_run,
)

from .evaluator import evaluate_saved_group_run, evaluate_saved_run


@dataclass(frozen=True)
class BenchmarkBatchResult:
    benchmark_directory: Path
    condition_results: pd.DataFrame


def _coverage_rate(case_directory: Path, layout_id: str) -> float | None:
    candidates = (
        case_directory
        / "visibility_maps"
        / layout_id
        / "coverage-metrics-1m-binary.json",
        case_directory / "visibility_maps" / layout_id / "coverage_metrics.json",
    )
    for path in candidates:
        if not path.is_file():
            continue
        document = json.loads(path.read_text(encoding="utf-8"))
        value = document.get("class_rates", {}).get("fully_visible")
        if value is not None:
            return float(value)
    return None


def discover_benchmark_conditions(
    cases_root: str | Path, case_id: str
) -> tuple[tuple[str, str], ...]:
    case_directory = resolve_case_path(cases_root, case_id)
    conditions = []
    for dataset_directory in sorted((case_directory / "datasets").glob("*")):
        observation_root = dataset_directory / "observations"
        if not (dataset_directory / "ground_truth.parquet").is_file():
            continue
        for layout_directory in sorted(observation_root.glob("*")):
            if (layout_directory / "observations.parquet").is_file():
                conditions.append((dataset_directory.name, layout_directory.name))
    return tuple(conditions)


def _read_json(path: Path) -> dict[str, object]:
    return json.loads(path.read_text(encoding="utf-8"))


# 保存済み全Dataset・配置へTrackerと群れ評価を適用する．
def run_benchmark_matrix(
    cases_root: str | Path,
    *,
    case_id: str,
    benchmark_id: str,
    tracker_methods: Iterable[str],
    tracker_settings: Mapping[str, JsonValue],
    tracker_seed: int,
    conditions: Iterable[tuple[str, str]] | None = None,
    overwrite: bool = False,
) -> BenchmarkBatchResult:
    validate_case_id(benchmark_id)
    case_directory = resolve_case_path(cases_root, case_id)
    environment_case = load_case(cases_root, case_id)
    farm_coordinates = tuple(
        (float(x_m), float(y_m))
        for x_m, y_m in environment_case.farm_boundary.polygon.exterior.coords
    )
    selected_conditions = tuple(
        conditions or discover_benchmark_conditions(cases_root, case_id)
    )
    if not selected_conditions:
        raise ValueError("No Dataset and camera layout conditions were found")
    methods = tuple(dict.fromkeys(str(method) for method in tracker_methods))
    if not methods:
        raise ValueError("at least one tracker method is required")

    rows: list[dict[str, object]] = []
    for dataset_id, layout_id in selected_conditions:
        validate_case_id(dataset_id)
        validate_case_id(layout_id)
        observation_path = (
            case_directory
            / "datasets"
            / dataset_id
            / "observations"
            / layout_id
            / "observations.parquet"
        )
        if not observation_path.is_file():
            raise FileNotFoundError(observation_path)
        observation_frames = load_observation_frames(observation_path)
        for method in methods:
            run_id = f"{dataset_id}__{layout_id}__{method}"
            validate_case_id(run_id)
            run_directory = case_directory / "runs" / run_id
            config = {
                **dict(tracker_settings),
                "tracker_id": method,
                "farm_boundary": farm_coordinates,
            }
            if not run_directory.exists() or overwrite:
                tracking_result = run_tracker(
                    create_tracker(method), observation_frames, config, tracker_seed
                )
                save_tracking_run(
                    cases_root,
                    case_id=case_id,
                    dataset_id=dataset_id,
                    run_id=run_id,
                    seed=tracker_seed,
                    tracker_config=config,
                    result=tracking_result,
                    observation_ref=str(observation_path.relative_to(case_directory)),
                    overwrite=overwrite,
                )
            if not (run_directory / "benchmark_metrics.json").exists() or overwrite:
                evaluate_saved_run(
                    cases_root,
                    case_id,
                    dataset_id,
                    run_id,
                    overwrite=overwrite,
                )
            if not (run_directory / "group_benchmark_metrics.json").exists() or overwrite:
                evaluate_saved_group_run(
                    cases_root,
                    case_id,
                    dataset_id,
                    run_id,
                    observation_source=observation_path,
                    overwrite=overwrite,
                )
            metrics = _read_json(run_directory / "group_benchmark_metrics.json")
            rows.append(
                {
                    "case_id": case_id,
                    "benchmark_id": benchmark_id,
                    "dataset_id": dataset_id,
                    "layout_id": layout_id,
                    "tracker_method": method,
                    "tracker_seed": tracker_seed,
                    "visibility_coverage_rate": _coverage_rate(
                        case_directory, layout_id
                    ),
                    **metrics,
                    "run_id": run_id,
                }
            )

    condition_results = pd.DataFrame(rows)
    destination = case_directory / "benchmarks" / benchmark_id
    if destination.exists() and not overwrite:
        existing = pd.read_parquet(
            destination / "condition_results.parquet", engine="pyarrow"
        )
        if existing.equals(condition_results):
            return BenchmarkBatchResult(destination, existing)
        raise FileExistsError(f"Benchmark summary already exists: {destination}")
    temporary = destination.parent / f".{benchmark_id}.tmp-{uuid4().hex}"
    temporary.mkdir(parents=True, exist_ok=False)
    try:
        condition_results.to_parquet(
            temporary / "condition_results.parquet", index=False, engine="pyarrow"
        )
        condition_results.to_csv(temporary / "summary.csv", index=False)
        manifest = {
            "schema_version": "1.0",
            "case_id": case_id,
            "benchmark_id": benchmark_id,
            "tracker_methods": list(methods),
            "tracker_seed": tracker_seed,
            "tracker_settings": dict(tracker_settings),
            "condition_count": len(selected_conditions),
            "run_count": len(condition_results),
            "ground_truth_supplied_to_tracker": False,
        }
        (temporary / "benchmark_manifest.json").write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        if destination.exists():
            shutil.rmtree(destination)
        temporary.replace(destination)
    except Exception:
        shutil.rmtree(temporary, ignore_errors=True)
        raise
    return BenchmarkBatchResult(destination, condition_results)
