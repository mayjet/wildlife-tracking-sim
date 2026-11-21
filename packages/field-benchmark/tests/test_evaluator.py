from __future__ import annotations

import pandas as pd
from shepherd_contracts import Observation, ObservationFrame, Position2D

from field_benchmark import (
    build_group_truth_table,
    evaluate_group_tracking_tables,
    evaluate_saved_run,
    evaluate_tracking_tables,
    extract_non_observation_events,
)
from field_tracker import ConstantVelocityTracker, run_tracker, save_tracking_run


def test_evaluator_computes_position_count_and_identity_metrics() -> None:
    truth = pd.DataFrame(
        {
            "timestamp_s": [0.0, 0.0, 1.0, 1.0],
            "truth_id": ["deer-a", "deer-b", "deer-a", "deer-b"],
            "x_m": [0.0, 10.0, 1.0, 11.0],
            "y_m": [0.0, 0.0, 0.0, 0.0],
        }
    )
    tracking = pd.DataFrame(
        {
            "timestamp_s": [0.0, 0.0, 1.0, 1.0],
            "track_id": ["track-a", "track-b", "track-a", "track-b"],
            "x_m": [0.1, 10.1, 1.1, 11.1],
            "y_m": [0.0, 0.0, 0.0, 0.0],
            "status": ["OBSERVED"] * 4,
        }
    )
    result = evaluate_tracking_tables(truth, tracking)
    assert result.metrics.detection_rate == 1.0
    assert result.metrics.mean_count_error == 0.0
    assert result.metrics.id_switch_count == 0
    assert result.metrics.mean_position_error_m is not None
    assert result.metrics.mean_position_error_m < 0.11


def test_tracker_run_storage_and_saved_evaluation_round_trip(tmp_path) -> None:
    cases_root = tmp_path / "cases"
    case_directory = cases_root / "case-a"
    dataset_directory = case_directory / "datasets" / "dataset-a"
    observation_directory = dataset_directory / "observations" / "layout-a"
    observation_directory.mkdir(parents=True)
    (case_directory / "runs").mkdir()
    truth = pd.DataFrame(
        {
            "timestamp_s": [0.0, 1.0],
            "truth_id": ["deer-a", "deer-a"],
            "x_m": [0.0, 1.0],
            "y_m": [0.0, 0.0],
        }
    )
    truth.to_parquet(dataset_directory / "ground_truth.parquet", index=False)
    frames = tuple(
        ObservationFrame(
            timestamp_s=timestamp_s,
            observations=(
                Observation(
                    timestamp_s=timestamp_s,
                    camera_id="camera-a",
                    observation_id=f"obs-{index}",
                    position=Position2D(x_m=timestamp_s, y_m=0.0),
                ),
            ),
        )
        for index, timestamp_s in enumerate((0.0, 1.0))
    )
    config = {
        "tracker_id": "storage-test",
        "confirmation_hits": 1,
        "confirmation_window": 1,
    }
    tracking_result = run_tracker(ConstantVelocityTracker(), frames, config, seed=4)
    run_directory = save_tracking_run(
        cases_root,
        case_id="case-a",
        dataset_id="dataset-a",
        run_id="run-a",
        seed=4,
        tracker_config=config,
        result=tracking_result,
        observation_ref="datasets/dataset-a/observations/layout-a/observations.parquet",
    )
    benchmark = evaluate_saved_run(cases_root, "case-a", "dataset-a", "run-a")

    assert (run_directory / "run_manifest.json").is_file()
    assert benchmark.metrics.detection_rate == 1.0


def test_group_truth_uses_member_centroid_instead_of_leader() -> None:
    truth = pd.DataFrame(
        {
            "timestamp_s": [0.0, 0.0, 0.0],
            "truth_id": ["leader", "follower-a", "follower-b"],
            "group_truth_id": ["herd-a"] * 3,
            "x_m": [0.0, 6.0, 12.0],
            "y_m": [0.0, 3.0, 0.0],
        }
    )
    groups = build_group_truth_table(truth)
    assert groups.iloc[0]["x_m"] == 6.0
    assert groups.iloc[0]["y_m"] == 1.0
    assert groups.iloc[0]["member_count"] == 3


def test_non_observation_events_extract_reacquisition() -> None:
    states = pd.DataFrame(
        {
            "timestamp_s": [0.0, 1.0, 2.0, 3.0],
            "group_truth_id": ["herd-a"] * 4,
            "observed": [True, False, False, True],
        }
    )
    events = extract_non_observation_events(states)
    assert len(events) == 1
    assert events.iloc[0]["hidden_duration_s"] == 3.0
    assert bool(events.iloc[0]["reacquired"])


def test_group_prediction_metrics_include_missing_predictions_as_failures() -> None:
    truth = pd.DataFrame(
        {
            "timestamp_s": [0.0, 0.0, 1.0, 1.0, 2.0, 2.0],
            "truth_id": ["a", "b"] * 3,
            "group_truth_id": ["herd-a"] * 6,
            "x_m": [0.0, 2.0, 1.0, 3.0, 2.0, 4.0],
            "y_m": [0.0] * 6,
        }
    )
    observations = pd.DataFrame(
        {
            "timestamp_s": [0.0, 2.0],
            "x_m": [0.0, 2.0],
            "y_m": [0.0, 0.0],
        }
    )
    tracking = pd.DataFrame(
        {
            "timestamp_s": [0.0, 2.0],
            "group_track_id": ["group-000001", "group-000001"],
            "x_m": [1.0, 3.0],
            "y_m": [0.0, 0.0],
        }
    )
    result = evaluate_group_tracking_tables(truth, observations, tracking)
    assert result.metrics.hidden_state_count == 1
    assert result.metrics.hidden_prediction_state_count == 0
    assert result.metrics.prediction_success_rate_10m == 0.0
    assert result.metrics.reacquisition_success_rate == 1.0


def test_group_prediction_score_degrades_with_known_offset() -> None:
    truth = pd.DataFrame(
        {
            "timestamp_s": [0.0, 1.0, 2.0],
            "truth_id": ["a"] * 3,
            "group_truth_id": ["herd-a"] * 3,
            "x_m": [0.0, 1.0, 2.0],
            "y_m": [0.0] * 3,
        }
    )
    observations = pd.DataFrame(
        {"timestamp_s": [0.0, 2.0], "x_m": [0.0, 2.0], "y_m": [0.0, 0.0]}
    )
    exact = pd.DataFrame(
        {
            "timestamp_s": [0.0, 1.0, 2.0],
            "group_track_id": ["group-a"] * 3,
            "x_m": [0.0, 1.0, 2.0],
            "y_m": [0.0] * 3,
        }
    )
    offset = exact.copy()
    offset.loc[offset["timestamp_s"] == 1.0, "x_m"] += 12.0
    exact_result = evaluate_group_tracking_tables(truth, observations, exact)
    offset_result = evaluate_group_tracking_tables(truth, observations, offset)
    assert exact_result.metrics.prediction_success_rate_10m == 1.0
    assert offset_result.metrics.prediction_success_rate_10m == 0.0
