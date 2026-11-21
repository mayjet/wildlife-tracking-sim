from __future__ import annotations

from dataclasses import asdict, dataclass
import json
from pathlib import Path

import numpy as np
import pandas as pd
from scipy.optimize import linear_sum_assignment

from field_environment import resolve_case_path, validate_case_id

from .group_metrics import GroupBenchmarkResult, evaluate_group_tracking_tables


@dataclass(frozen=True)
class TrackingMetrics:
    matched_state_count: int
    ground_truth_state_count: int
    track_state_count: int
    detection_rate: float
    mean_position_error_m: float | None
    rmse_position_error_m: float | None
    p95_position_error_m: float | None
    mean_count_error: float
    id_switch_count: int


@dataclass(frozen=True)
class BenchmarkResult:
    metrics: TrackingMetrics
    assignments: pd.DataFrame


# Evaluatorだけが真値とTracker出力を対応付けて評価指標を計算する．
def evaluate_tracking_tables(
    ground_truth: pd.DataFrame,
    tracking: pd.DataFrame,
    *,
    maximum_match_distance_m: float = 20.0,
) -> BenchmarkResult:
    required_truth = {"timestamp_s", "truth_id", "x_m", "y_m"}
    required_tracking = {"timestamp_s", "track_id", "x_m", "y_m"}
    if missing := required_truth - set(ground_truth.columns):
        raise ValueError(f"Ground Truth columns are missing: {sorted(missing)}")
    if missing := required_tracking - set(tracking.columns):
        raise ValueError(f"tracking columns are missing: {sorted(missing)}")
    timestamps = sorted(
        set(ground_truth["timestamp_s"].astype(float))
        | set(tracking["timestamp_s"].astype(float))
    )
    assignment_rows = []
    count_errors = []
    previous_track_by_truth: dict[str, str] = {}
    id_switch_count = 0
    for timestamp_s in timestamps:
        truth_rows = ground_truth[ground_truth["timestamp_s"] == timestamp_s].reset_index(drop=True)
        timestamp_mask = tracking["timestamp_s"] == timestamp_s
        if "status" in tracking.columns:
            timestamp_mask &= tracking["status"] != "TERMINATED"
        track_rows = tracking[timestamp_mask].reset_index(drop=True)
        count_errors.append(abs(len(track_rows) - len(truth_rows)))
        if truth_rows.empty or track_rows.empty:
            continue
        truth_xy = truth_rows[["x_m", "y_m"]].to_numpy(dtype=float)
        track_xy = track_rows[["x_m", "y_m"]].to_numpy(dtype=float)
        distances = np.linalg.norm(truth_xy[:, None, :] - track_xy[None, :, :], axis=2)
        truth_indices, track_indices = linear_sum_assignment(distances)
        for truth_index, track_index in zip(truth_indices, track_indices):
            distance_m = float(distances[truth_index, track_index])
            if distance_m > maximum_match_distance_m:
                continue
            truth_id = str(truth_rows.iloc[truth_index]["truth_id"])
            track_id = str(track_rows.iloc[track_index]["track_id"])
            previous = previous_track_by_truth.get(truth_id)
            if previous is not None and previous != track_id:
                id_switch_count += 1
            previous_track_by_truth[truth_id] = track_id
            assignment_rows.append(
                {
                    "timestamp_s": float(timestamp_s),
                    "truth_id": truth_id,
                    "track_id": track_id,
                    "position_error_m": distance_m,
                }
            )
    assignments = pd.DataFrame(
        assignment_rows,
        columns=("timestamp_s", "truth_id", "track_id", "position_error_m"),
    )
    errors = assignments["position_error_m"].to_numpy(dtype=float)
    truth_count = len(ground_truth)
    metrics = TrackingMetrics(
        matched_state_count=len(assignments),
        ground_truth_state_count=truth_count,
        track_state_count=len(tracking),
        detection_rate=(len(assignments) / truth_count if truth_count else 0.0),
        mean_position_error_m=(float(np.mean(errors)) if len(errors) else None),
        rmse_position_error_m=(
            float(np.sqrt(np.mean(np.square(errors)))) if len(errors) else None
        ),
        p95_position_error_m=(float(np.percentile(errors, 95)) if len(errors) else None),
        mean_count_error=float(np.mean(count_errors)) if count_errors else 0.0,
        id_switch_count=id_switch_count,
    )
    return BenchmarkResult(metrics=metrics, assignments=assignments)


def evaluate_saved_run(
    cases_root: str | Path,
    case_id: str,
    dataset_id: str,
    run_id: str,
    *,
    maximum_match_distance_m: float = 20.0,
    overwrite: bool = False,
) -> BenchmarkResult:
    validate_case_id(dataset_id)
    validate_case_id(run_id)
    case_directory = resolve_case_path(cases_root, case_id)
    ground_truth_path = case_directory / "datasets" / dataset_id / "ground_truth.parquet"
    run_directory = case_directory / "runs" / run_id
    tracking_path = run_directory / "tracking.parquet"
    result = evaluate_tracking_tables(
        pd.read_parquet(ground_truth_path, engine="pyarrow"),
        pd.read_parquet(tracking_path, engine="pyarrow"),
        maximum_match_distance_m=maximum_match_distance_m,
    )
    metrics_path = run_directory / "benchmark_metrics.json"
    assignments_path = run_directory / "benchmark_assignments.parquet"
    if (metrics_path.exists() or assignments_path.exists()) and not overwrite:
        raise FileExistsError(f"benchmark result already exists: {run_directory}")
    metrics_path.write_text(
        json.dumps(asdict(result.metrics), ensure_ascii=False, indent=2), encoding="utf-8"
    )
    result.assignments.to_parquet(assignments_path, index=False, engine="pyarrow")
    return result


def evaluate_saved_group_run(
    cases_root: str | Path,
    case_id: str,
    dataset_id: str,
    run_id: str,
    *,
    observation_source: str | Path | None = None,
    maximum_group_match_distance_m: float = 100.0,
    maximum_observation_match_distance_m: float = 20.0,
    overwrite: bool = False,
) -> GroupBenchmarkResult:
    validate_case_id(dataset_id)
    validate_case_id(run_id)
    case_directory = resolve_case_path(cases_root, case_id)
    dataset_directory = case_directory / "datasets" / dataset_id
    run_directory = case_directory / "runs" / run_id
    if observation_source is None:
        manifest = json.loads(
            (run_directory / "run_manifest.json").read_text(encoding="utf-8")
        )
        input_refs = manifest.get("input_data_refs", [])
        if not input_refs:
            raise ValueError("Run manifest does not contain an Observation reference")
        observation_path = case_directory / str(input_refs[0])
    else:
        observation_path = Path(observation_source)
        if observation_path.is_dir():
            observation_path = observation_path / "observations.parquet"
    result = evaluate_group_tracking_tables(
        pd.read_parquet(dataset_directory / "ground_truth.parquet", engine="pyarrow"),
        pd.read_parquet(observation_path, engine="pyarrow"),
        pd.read_parquet(run_directory / "group_tracking.parquet", engine="pyarrow"),
        maximum_group_match_distance_m=maximum_group_match_distance_m,
        maximum_observation_match_distance_m=maximum_observation_match_distance_m,
    )
    outputs = {
        "group_benchmark_metrics.json": json.dumps(
            asdict(result.metrics), ensure_ascii=False, indent=2
        ),
        "group_truth.parquet": result.group_truth,
        "group_benchmark_assignments.parquet": result.assignments,
        "group_observation_events.parquet": result.non_observation_events,
        "group_duration_summary.parquet": result.duration_summary,
    }
    if any((run_directory / name).exists() for name in outputs) and not overwrite:
        raise FileExistsError(f"group benchmark result already exists: {run_directory}")
    for name, output in outputs.items():
        path = run_directory / name
        if isinstance(output, str):
            path.write_text(output, encoding="utf-8")
        else:
            output.to_parquet(path, index=False, engine="pyarrow")
    return result
