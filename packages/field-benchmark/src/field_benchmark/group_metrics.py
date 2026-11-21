from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd
from scipy.optimize import linear_sum_assignment

from .events import extract_non_observation_events
from .group_truth import build_group_observation_table, build_group_truth_table


@dataclass(frozen=True)
class GroupTrackingMetrics:
    group_truth_state_count: int
    matched_group_state_count: int
    hidden_state_count: int
    hidden_prediction_state_count: int
    mean_position_error_m: float | None
    mean_hidden_position_error_m: float | None
    prediction_success_rate_5m: float
    prediction_success_rate_10m: float
    prediction_success_rate_20m: float
    non_observation_event_count: int
    reacquisition_event_count: int
    reacquisition_success_count: int
    reacquisition_success_rate: float | None


@dataclass(frozen=True)
class GroupBenchmarkResult:
    metrics: GroupTrackingMetrics
    group_truth: pd.DataFrame
    assignments: pd.DataFrame
    non_observation_events: pd.DataFrame
    duration_summary: pd.DataFrame


ASSIGNMENT_COLUMNS = (
    "timestamp_s",
    "group_truth_id",
    "group_track_id",
    "truth_x_m",
    "truth_y_m",
    "estimated_x_m",
    "estimated_y_m",
    "position_error_m",
    "observed",
    "hidden_elapsed_s",
    "prediction_available",
)


def _duration_label(hidden_elapsed_s: float) -> str:
    if hidden_elapsed_s <= 5.0:
        return "0-5s"
    if hidden_elapsed_s <= 15.0:
        return "5-15s"
    if hidden_elapsed_s <= 30.0:
        return "15-30s"
    return "30s+"


def _prediction_success(assignments: pd.DataFrame, threshold_m: float) -> float:
    hidden = assignments[~assignments["observed"]]
    if hidden.empty:
        return 0.0
    successful = hidden["prediction_available"] & (
        hidden["position_error_m"] <= threshold_m
    )
    return float(successful.sum() / len(hidden))


def _duration_summary(assignments: pd.DataFrame) -> pd.DataFrame:
    hidden = assignments[~assignments["observed"]].copy()
    columns = (
        "duration_bin",
        "state_count",
        "prediction_count",
        "mean_position_error_m",
        "prediction_success_rate_10m",
    )
    if hidden.empty:
        return pd.DataFrame(columns=columns)
    hidden["duration_bin"] = hidden["hidden_elapsed_s"].map(_duration_label)
    rows = []
    for duration_bin in ("0-5s", "5-15s", "15-30s", "30s+"):
        states = hidden[hidden["duration_bin"] == duration_bin]
        if states.empty:
            continue
        predicted = states[states["prediction_available"]]
        success = states["prediction_available"] & (
            states["position_error_m"] <= 10.0
        )
        rows.append(
            {
                "duration_bin": duration_bin,
                "state_count": int(len(states)),
                "prediction_count": int(states["prediction_available"].sum()),
                "mean_position_error_m": (
                    float(predicted["position_error_m"].mean())
                    if not predicted.empty
                    else None
                ),
                "prediction_success_rate_10m": float(success.sum() / len(states)),
            }
        )
    return pd.DataFrame(rows, columns=columns)


def _reacquisition_metrics(
    events: pd.DataFrame, assignments: pd.DataFrame
) -> tuple[pd.DataFrame, int, int]:
    if events.empty:
        enriched = events.assign(
            group_track_id_before=pd.Series(dtype="object"),
            group_track_id_after=pd.Series(dtype="object"),
            reacquisition_success=pd.Series(dtype="bool"),
        )
        return enriched, 0, 0
    enriched = events.copy()
    before_ids = []
    after_ids = []
    successes = []
    for event in enriched.itertuples(index=False):
        group_assignments = assignments[
            assignments["group_truth_id"] == event.group_truth_id
        ]
        before = group_assignments[
            group_assignments["timestamp_s"] == event.last_observed_s
        ]
        after = group_assignments[
            group_assignments["timestamp_s"] == event.reacquired_at_s
        ]
        before_id = (
            None
            if before.empty or not bool(before.iloc[0]["prediction_available"])
            else before.iloc[0]["group_track_id"]
        )
        after_id = (
            None
            if after.empty or not bool(after.iloc[0]["prediction_available"])
            else after.iloc[0]["group_track_id"]
        )
        success = bool(
            event.reacquired
            and before_id is not None
            and after_id is not None
            and before_id == after_id
        )
        before_ids.append(before_id)
        after_ids.append(after_id)
        successes.append(success)
    enriched["group_track_id_before"] = before_ids
    enriched["group_track_id_after"] = after_ids
    enriched["reacquisition_success"] = successes
    eligible = enriched[enriched["reacquired"]]
    return enriched, len(eligible), int(eligible["reacquisition_success"].sum())


# 群れ中心，非観測時間，再捕捉を主単位として追跡結果を評価する．
def evaluate_group_tracking_tables(
    ground_truth: pd.DataFrame,
    observations: pd.DataFrame,
    group_tracking: pd.DataFrame,
    *,
    maximum_group_match_distance_m: float = 100.0,
    maximum_observation_match_distance_m: float = 20.0,
) -> GroupBenchmarkResult:
    required_tracking = {"timestamp_s", "group_track_id", "x_m", "y_m"}
    if missing := required_tracking - set(group_tracking.columns):
        raise ValueError(f"group tracking columns are missing: {sorted(missing)}")
    if maximum_group_match_distance_m <= 0.0:
        raise ValueError("maximum_group_match_distance_m must be positive")

    group_truth = build_group_truth_table(ground_truth)
    observation_states = build_group_observation_table(
        ground_truth,
        observations,
        maximum_observation_match_distance_m=maximum_observation_match_distance_m,
    )
    observed_lookup = {
        (float(row.timestamp_s), str(row.group_truth_id)): bool(row.observed)
        for row in observation_states.itertuples(index=False)
    }
    tracking_by_time = {
        float(timestamp_s): frame
        for timestamp_s, frame in group_tracking.groupby("timestamp_s", sort=False)
    }
    last_observed_by_group: dict[str, float] = {}
    first_timestamp_by_group: dict[str, float] = {}
    assignment_rows: list[dict[str, object]] = []
    for timestamp_s, truth_frame in group_truth.groupby("timestamp_s", sort=True):
        truth_frame = truth_frame.reset_index(drop=True)
        track_frame = tracking_by_time.get(float(timestamp_s))
        track_frame = (
            pd.DataFrame(columns=group_tracking.columns)
            if track_frame is None
            else track_frame.reset_index(drop=True)
        )
        matches: dict[int, tuple[int, float]] = {}
        if not track_frame.empty:
            truth_xy = truth_frame[["x_m", "y_m"]].to_numpy(dtype=float)
            track_xy = track_frame[["x_m", "y_m"]].to_numpy(dtype=float)
            distances = np.linalg.norm(
                truth_xy[:, None, :] - track_xy[None, :, :], axis=2
            )
            truth_indices, track_indices = linear_sum_assignment(distances)
            matches = {
                int(truth_index): (int(track_index), float(distances[truth_index, track_index]))
                for truth_index, track_index in zip(truth_indices, track_indices)
                if float(distances[truth_index, track_index])
                <= maximum_group_match_distance_m
            }
        for truth_index, truth in truth_frame.iterrows():
            group_truth_id = str(truth["group_truth_id"])
            first_timestamp_by_group.setdefault(group_truth_id, float(timestamp_s))
            observed = observed_lookup.get(
                (float(timestamp_s), group_truth_id), False
            )
            if observed:
                last_observed_by_group[group_truth_id] = float(timestamp_s)
                hidden_elapsed_s = 0.0
            else:
                hidden_elapsed_s = float(timestamp_s) - last_observed_by_group.get(
                    group_truth_id, first_timestamp_by_group[group_truth_id]
                )
            match = matches.get(int(truth_index))
            if match is None:
                track_id = None
                estimated_x_m = None
                estimated_y_m = None
                error_m = np.nan
            else:
                track_index, error_m = match
                track = track_frame.iloc[track_index]
                track_id = str(track["group_track_id"])
                estimated_x_m = float(track["x_m"])
                estimated_y_m = float(track["y_m"])
            assignment_rows.append(
                {
                    "timestamp_s": float(timestamp_s),
                    "group_truth_id": group_truth_id,
                    "group_track_id": track_id,
                    "truth_x_m": float(truth["x_m"]),
                    "truth_y_m": float(truth["y_m"]),
                    "estimated_x_m": estimated_x_m,
                    "estimated_y_m": estimated_y_m,
                    "position_error_m": error_m,
                    "observed": observed,
                    "hidden_elapsed_s": hidden_elapsed_s,
                    "prediction_available": match is not None,
                }
            )
    assignments = pd.DataFrame(assignment_rows, columns=ASSIGNMENT_COLUMNS)
    events = extract_non_observation_events(observation_states)
    events, reacquisition_count, reacquisition_success_count = _reacquisition_metrics(
        events, assignments
    )
    predicted = assignments[assignments["prediction_available"]]
    hidden = assignments[~assignments["observed"]]
    hidden_predicted = hidden[hidden["prediction_available"]]
    metrics = GroupTrackingMetrics(
        group_truth_state_count=len(assignments),
        matched_group_state_count=int(assignments["prediction_available"].sum()),
        hidden_state_count=len(hidden),
        hidden_prediction_state_count=int(hidden["prediction_available"].sum()),
        mean_position_error_m=(
            float(predicted["position_error_m"].mean())
            if not predicted.empty
            else None
        ),
        mean_hidden_position_error_m=(
            float(hidden_predicted["position_error_m"].mean())
            if not hidden_predicted.empty
            else None
        ),
        prediction_success_rate_5m=_prediction_success(assignments, 5.0),
        prediction_success_rate_10m=_prediction_success(assignments, 10.0),
        prediction_success_rate_20m=_prediction_success(assignments, 20.0),
        non_observation_event_count=len(events),
        reacquisition_event_count=reacquisition_count,
        reacquisition_success_count=reacquisition_success_count,
        reacquisition_success_rate=(
            reacquisition_success_count / reacquisition_count
            if reacquisition_count
            else None
        ),
    )
    return GroupBenchmarkResult(
        metrics=metrics,
        group_truth=group_truth,
        assignments=assignments,
        non_observation_events=events,
        duration_summary=_duration_summary(assignments),
    )
