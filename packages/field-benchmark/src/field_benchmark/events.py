from __future__ import annotations

import pandas as pd


EVENT_COLUMNS = (
    "event_id",
    "group_truth_id",
    "last_observed_s",
    "hidden_start_s",
    "hidden_end_s",
    "reacquired_at_s",
    "hidden_duration_s",
    "reacquired",
)


# 群れごとの連続した非観測区間と再観測時刻を抽出する．
def extract_non_observation_events(group_observations: pd.DataFrame) -> pd.DataFrame:
    required = {"timestamp_s", "group_truth_id", "observed"}
    if missing := required - set(group_observations.columns):
        raise ValueError(f"group observation columns are missing: {sorted(missing)}")
    rows: list[dict[str, object]] = []
    event_number = 1
    for group_truth_id, states in group_observations.groupby(
        "group_truth_id", sort=True
    ):
        states = states.sort_values("timestamp_s").reset_index(drop=True)
        timestamps = states["timestamp_s"].astype(float).to_numpy()
        if len(timestamps) > 1 and (timestamps[1:] <= timestamps[:-1]).any():
            raise ValueError("group observation timestamps must be strictly increasing")
        last_observed_s: float | None = None
        hidden_start_index: int | None = None
        for index, state in states.iterrows():
            timestamp_s = float(state["timestamp_s"])
            observed = bool(state["observed"])
            if observed:
                if hidden_start_index is not None:
                    hidden_start_s = float(states.iloc[hidden_start_index]["timestamp_s"])
                    hidden_end_s = float(states.iloc[index - 1]["timestamp_s"])
                    duration_s = (
                        timestamp_s - last_observed_s
                        if last_observed_s is not None
                        else timestamp_s - hidden_start_s
                    )
                    rows.append(
                        {
                            "event_id": f"hidden-{event_number:06d}",
                            "group_truth_id": str(group_truth_id),
                            "last_observed_s": last_observed_s,
                            "hidden_start_s": hidden_start_s,
                            "hidden_end_s": hidden_end_s,
                            "reacquired_at_s": timestamp_s,
                            "hidden_duration_s": float(max(duration_s, 0.0)),
                            "reacquired": True,
                        }
                    )
                    event_number += 1
                    hidden_start_index = None
                last_observed_s = timestamp_s
            elif hidden_start_index is None:
                hidden_start_index = index
        if hidden_start_index is not None:
            hidden_start_s = float(states.iloc[hidden_start_index]["timestamp_s"])
            hidden_end_s = float(states.iloc[-1]["timestamp_s"])
            duration_s = (
                hidden_end_s - last_observed_s
                if last_observed_s is not None
                else hidden_end_s - hidden_start_s
            )
            rows.append(
                {
                    "event_id": f"hidden-{event_number:06d}",
                    "group_truth_id": str(group_truth_id),
                    "last_observed_s": last_observed_s,
                    "hidden_start_s": hidden_start_s,
                    "hidden_end_s": hidden_end_s,
                    "reacquired_at_s": None,
                    "hidden_duration_s": float(max(duration_s, 0.0)),
                    "reacquired": False,
                }
            )
            event_number += 1
    return pd.DataFrame(rows, columns=EVENT_COLUMNS)
