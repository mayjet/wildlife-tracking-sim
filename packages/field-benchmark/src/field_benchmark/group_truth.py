from __future__ import annotations

import numpy as np
import pandas as pd
from scipy.optimize import linear_sum_assignment


GROUP_TRUTH_COLUMNS = (
    "timestamp_s",
    "group_truth_id",
    "x_m",
    "y_m",
    "member_count",
    "member_truth_ids",
    "spread_radius_m",
)

GROUP_OBSERVATION_COLUMNS = (
    "timestamp_s",
    "group_truth_id",
    "observed",
    "observed_member_count",
    "member_count",
)


def _require_columns(table: pd.DataFrame, required: set[str], label: str) -> None:
    if missing := required - set(table.columns):
        raise ValueError(f"{label} columns are missing: {sorted(missing)}")


# 個体真値を時刻ごとの群れ中心と広がりへ集約する．
def build_group_truth_table(ground_truth: pd.DataFrame) -> pd.DataFrame:
    _require_columns(
        ground_truth,
        {"timestamp_s", "truth_id", "group_truth_id", "x_m", "y_m"},
        "Ground Truth",
    )
    rows: list[dict[str, object]] = []
    grouped = ground_truth.dropna(subset=["group_truth_id"]).groupby(
        ["timestamp_s", "group_truth_id"], sort=True
    )
    for (timestamp_s, group_truth_id), members in grouped:
        positions = members[["x_m", "y_m"]].to_numpy(dtype=float)
        center = np.mean(positions, axis=0)
        distances = np.linalg.norm(positions - center, axis=1)
        rows.append(
            {
                "timestamp_s": float(timestamp_s),
                "group_truth_id": str(group_truth_id),
                "x_m": float(center[0]),
                "y_m": float(center[1]),
                "member_count": int(len(members)),
                "member_truth_ids": sorted(members["truth_id"].astype(str).tolist()),
                "spread_radius_m": float(np.max(distances)) if len(distances) else 0.0,
            }
        )
    return pd.DataFrame(rows, columns=GROUP_TRUTH_COLUMNS)


def _deduplicate_observations(
    observations: pd.DataFrame, tolerance_m: float
) -> np.ndarray:
    positions = observations[["x_m", "y_m"]].to_numpy(dtype=float)
    representatives: list[np.ndarray] = []
    for position in positions:
        if not any(
            float(np.linalg.norm(position - representative)) <= tolerance_m
            for representative in representatives
        ):
            representatives.append(position)
    if not representatives:
        return np.empty((0, 2), dtype=float)
    return np.asarray(representatives, dtype=float)


# Evaluator内だけで観測位置を個体真値へ対応付け，群れの観測状態を求める．
def build_group_observation_table(
    ground_truth: pd.DataFrame,
    observations: pd.DataFrame,
    *,
    maximum_observation_match_distance_m: float = 20.0,
    duplicate_observation_tolerance_m: float = 0.05,
) -> pd.DataFrame:
    if maximum_observation_match_distance_m <= 0.0:
        raise ValueError("maximum_observation_match_distance_m must be positive")
    if duplicate_observation_tolerance_m < 0.0:
        raise ValueError("duplicate_observation_tolerance_m cannot be negative")
    _require_columns(
        ground_truth,
        {"timestamp_s", "truth_id", "group_truth_id", "x_m", "y_m"},
        "Ground Truth",
    )
    _require_columns(observations, {"timestamp_s", "x_m", "y_m"}, "Observation")

    rows: list[dict[str, object]] = []
    observations_by_time = {
        float(timestamp_s): frame
        for timestamp_s, frame in observations.groupby("timestamp_s", sort=False)
    }
    for timestamp_s, truth_frame in ground_truth.groupby("timestamp_s", sort=True):
        truth_frame = truth_frame.dropna(subset=["group_truth_id"]).reset_index(drop=True)
        if truth_frame.empty:
            continue
        observed_truth_indices: set[int] = set()
        observation_frame = observations_by_time.get(float(timestamp_s))
        if observation_frame is not None and not observation_frame.empty:
            observation_xy = _deduplicate_observations(
                observation_frame, duplicate_observation_tolerance_m
            )
            truth_xy = truth_frame[["x_m", "y_m"]].to_numpy(dtype=float)
            if len(observation_xy):
                distances = np.linalg.norm(
                    truth_xy[:, None, :] - observation_xy[None, :, :], axis=2
                )
                truth_indices, observation_indices = linear_sum_assignment(distances)
                observed_truth_indices.update(
                    int(truth_index)
                    for truth_index, observation_index in zip(
                        truth_indices, observation_indices
                    )
                    if float(distances[truth_index, observation_index])
                    <= maximum_observation_match_distance_m
                )
        for group_truth_id, members in truth_frame.groupby("group_truth_id", sort=True):
            member_indices = set(int(index) for index in members.index)
            observed_member_count = len(member_indices & observed_truth_indices)
            rows.append(
                {
                    "timestamp_s": float(timestamp_s),
                    "group_truth_id": str(group_truth_id),
                    "observed": observed_member_count > 0,
                    "observed_member_count": observed_member_count,
                    "member_count": int(len(members)),
                }
            )
    return pd.DataFrame(rows, columns=GROUP_OBSERVATION_COLUMNS)
