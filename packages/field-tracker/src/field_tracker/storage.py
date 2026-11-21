from __future__ import annotations

import json
import shutil
from pathlib import Path
from uuid import uuid4

import numpy as np
import pandas as pd
from pydantic_core import to_jsonable_python
from shepherd_contracts import (
    AgeClass,
    AlgorithmSpec,
    Observation,
    ObservationFrame,
    Position2D,
    RunManifest,
    RunStatus,
)

from field_environment import resolve_case_path, validate_case_id

from .runner import TrackingResult


def load_observation_frames(
    observation_source: str | Path,
    *,
    duration_s: float | None = None,
    step_s: float | None = None,
) -> tuple[ObservationFrame, ...]:
    source = Path(observation_source)
    parquet = source / "observations.parquet" if source.is_dir() else source
    table = pd.read_parquet(parquet, engine="pyarrow")
    forbidden = {"truth_id", "group_truth_id", "is_group_leader"} & set(table.columns)
    if forbidden:
        raise ValueError(f"Observation input contains Ground Truth fields: {sorted(forbidden)}")
    if duration_s is None or step_s is None:
        manifest_candidates = [source / "manifest.json"] if source.is_dir() else []
        manifest_candidates.extend(source.parents[index] / "manifest.json" for index in range(min(3, len(source.parents))))
        for manifest_path in manifest_candidates:
            if not manifest_path.is_file():
                continue
            document = json.loads(manifest_path.read_text(encoding="utf-8"))
            duration_s = duration_s or document.get("duration_s")
            step_s = step_s or document.get("simulation_step_s")
            if duration_s is not None and step_s is not None:
                break
    timestamps = sorted(float(value) for value in table["timestamp_s"].unique())
    if duration_s is not None and step_s is not None:
        timestamps = list(np.arange(round(duration_s / step_s) + 1) * step_s)
    grouped = {
        float(timestamp_s): group
        for timestamp_s, group in table.groupby("timestamp_s", sort=True)
    }
    frames = []
    for timestamp_s in timestamps:
        observations = []
        group = grouped.get(float(timestamp_s))
        if group is not None:
            for row in group.itertuples(index=False):
                observations.append(
                    Observation(
                        timestamp_s=float(row.timestamp_s),
                        camera_id=str(row.camera_id),
                        observation_id=str(row.observation_id),
                        position=Position2D(x_m=float(row.x_m), y_m=float(row.y_m)),
                        age_class=AgeClass(str(row.age_class)),
                    )
                )
        frames.append(ObservationFrame(timestamp_s=float(timestamp_s), observations=tuple(observations)))
    return tuple(frames)


def _tracking_dataframe(result: TrackingResult) -> pd.DataFrame:
    states = {(item.timestamp_s, item.track_id): item for item in result.internal_states}
    rows = []
    for frame in result.frames:
        for track in frame.tracks:
            state = states.get((frame.timestamp_s, track.track_id))
            rows.append(
                {
                    "timestamp_s": frame.timestamp_s,
                    "track_id": track.track_id,
                    "x_m": track.position.x_m,
                    "y_m": track.position.y_m,
                    "velocity_x_mps": None if track.velocity is None else track.velocity.x_mps,
                    "velocity_y_mps": None if track.velocity is None else track.velocity.y_mps,
                    "status": track.status.value,
                    "lifecycle_state": None if state is None else state.lifecycle_state.value,
                    "association_confidence": None if state is None else state.association_confidence,
                    "hit_count": None if state is None else state.hit_count,
                    "missed_count": None if state is None else state.missed_count,
                }
            )
    return pd.DataFrame(rows)


def save_tracking_run(
    cases_root: str | Path,
    *,
    case_id: str,
    dataset_id: str,
    run_id: str,
    seed: int,
    tracker_config: dict,
    result: TrackingResult,
    observation_ref: str,
    overwrite: bool = False,
) -> Path:
    validate_case_id(run_id)
    case_directory = resolve_case_path(cases_root, case_id)
    destination = case_directory / "runs" / run_id
    if destination.exists() and not overwrite:
        raise FileExistsError(f"Run already exists: {destination}")
    artifact_refs = tuple(
        f"runs/{run_id}/{name}"
        for name in (
            "tracking.parquet",
            "group_tracking.parquet",
            "lifecycle_events.parquet",
            "association_events.parquet",
            "group_events.parquet",
        )
    )
    json_tracker_config = to_jsonable_python(tracker_config)
    manifest = RunManifest(
        schema_version="1.0",
        case_id=case_id,
        dataset_id=dataset_id,
        run_id=run_id,
        seed=seed,
        algorithm=AlgorithmSpec(
            name=result.tracker_id,
            version="0.1.0",
            parameters=json_tracker_config,
        ),
        input_data_refs=(observation_ref,),
        artifact_refs=artifact_refs,
        environment={"ground_truth_supplied_to_tracker": False},
        status=RunStatus.COMPLETED,
    )
    temporary = destination.parent / f".{run_id}.tmp-{uuid4().hex}"
    temporary.mkdir(parents=True)
    try:
        _tracking_dataframe(result).to_parquet(temporary / "tracking.parquet", index=False)
        group_rows = []
        for frame in result.frames:
            for group in frame.groups:
                group_rows.append(
                    {
                        "timestamp_s": frame.timestamp_s,
                        "group_track_id": group.group_track_id,
                        "x_m": group.center.x_m,
                        "y_m": group.center.y_m,
                        "estimated_member_count": group.estimated_member_count,
                        "observed_member_count": group.observed_member_count,
                        "member_track_ids": list(group.member_track_ids),
                        "status": group.status.value,
                    }
                )
        pd.DataFrame(
            group_rows,
            columns=(
                "timestamp_s",
                "group_track_id",
                "x_m",
                "y_m",
                "estimated_member_count",
                "observed_member_count",
                "member_track_ids",
                "status",
            ),
        ).to_parquet(temporary / "group_tracking.parquet", index=False)
        pd.DataFrame(
            [
                {
                    **event.__dict__,
                    "previous_state": None if event.previous_state is None else event.previous_state.value,
                    "current_state": event.current_state.value,
                }
                for event in result.lifecycle_events
            ]
        ).to_parquet(temporary / "lifecycle_events.parquet", index=False)
        pd.DataFrame([event.__dict__ for event in result.association_events]).to_parquet(
            temporary / "association_events.parquet", index=False
        )
        pd.DataFrame(
            [event.__dict__ for event in result.group_events],
            columns=(
                "timestamp_s",
                "event_type",
                "group_track_id",
                "related_group_track_ids",
                "member_track_ids",
            ),
        ).to_parquet(temporary / "group_events.parquet", index=False)
        (temporary / "run_manifest.json").write_text(
            manifest.model_dump_json(indent=2), encoding="utf-8"
        )
        (temporary / "tracker_config.json").write_text(
            json.dumps(json_tracker_config, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        if destination.exists():
            shutil.rmtree(destination)
        temporary.replace(destination)
    except Exception:
        shutil.rmtree(temporary, ignore_errors=True)
        raise
    return destination
