from __future__ import annotations

import hashlib
import json
import shutil
from dataclasses import dataclass
from pathlib import Path
from uuid import uuid4

import pandas as pd
from shepherd_contracts import (
    AgeClass,
    DatasetManifest,
    GroundTruthFrame,
    GroundTruthState,
    Position3D,
    Velocity2D,
)

from field_environment import load_case, resolve_case_path, validate_case_id

from .config import SimulationConfig
from .simulator import SimulationResult, simulate


@dataclass(frozen=True)
class SavedDataset:
    manifest: DatasetManifest
    frames: tuple[GroundTruthFrame, ...]
    directory: Path


def _validate_dataset_id(dataset_id: str) -> str:
    return validate_case_id(dataset_id)


def _case_hash(case_directory: Path) -> str:
    digest = hashlib.sha256()
    for filename in (
        "case.yaml",
        "terrain.tif",
        "farm_boundary.geojson",
        "buildings.geojson",
        "forest.geojson",
        "traversability.tif",
    ):
        path = case_directory / filename
        if path.is_file():
            digest.update(filename.encode("utf-8"))
            digest.update(path.read_bytes())
    return digest.hexdigest()


def _frames_to_dataframe(frames: tuple[GroundTruthFrame, ...]) -> pd.DataFrame:
    rows = []
    for frame in frames:
        for state in frame.states:
            position = state.position
            rows.append(
                {
                    "timestamp_s": state.timestamp_s,
                    "truth_id": state.truth_id,
                    "group_truth_id": state.group_truth_id,
                    "is_group_leader": state.is_group_leader,
                    "x_m": position.x_m,
                    "y_m": position.y_m,
                    "z_m": position.z_m if isinstance(position, Position3D) else None,
                    "velocity_x_mps": None if state.velocity is None else state.velocity.x_mps,
                    "velocity_y_mps": None if state.velocity is None else state.velocity.y_mps,
                    "age_class": state.age_class.value,
                }
            )
    return pd.DataFrame(rows)


def save_simulation_dataset(
    cases_root: str | Path,
    result: SimulationResult,
    *,
    overwrite: bool = False,
) -> SavedDataset:
    case_directory = resolve_case_path(cases_root, result.config.case_id)
    dataset_id = _validate_dataset_id(result.config.dataset_id)
    destination = case_directory / "datasets" / dataset_id
    if destination.exists() and not overwrite:
        raise FileExistsError(f"Dataset already exists: {destination}")
    ground_truth_ref = f"datasets/{dataset_id}/ground_truth.parquet"
    observation_ref = f"datasets/{dataset_id}/observations.parquet"
    manifest = DatasetManifest(
        schema_version="1.0",
        case_id=result.config.case_id,
        dataset_id=dataset_id,
        seed=result.config.seed,
        duration_s=result.config.duration_s,
        simulation_step_s=result.config.step_s,
        scenario_config={
            "case_sha256": _case_hash(case_directory),
            "individual_count": 1,
            "truth_id": result.config.truth_id,
            "motion": result.config.motion.model_dump(mode="json"),
            "age_class": result.config.age_class.value,
            "surface_interpolation": "piecewise triangular, matching TerrainMesh faces",
            "observation_data_status": "not_generated_phase6",
        },
        observation_data_ref=observation_ref,
        ground_truth_data_ref=ground_truth_ref,
    )
    temporary = destination.parent / f".{dataset_id}.tmp-{uuid4().hex}"
    temporary.mkdir()
    try:
        _frames_to_dataframe(result.frames).to_parquet(
            temporary / "ground_truth.parquet", index=False, engine="pyarrow"
        )
        (temporary / "manifest.json").write_text(
            manifest.model_dump_json(indent=2), encoding="utf-8"
        )
        (temporary / "simulation_config.json").write_text(
            result.config.model_dump_json(indent=2), encoding="utf-8"
        )
        if destination.exists():
            shutil.rmtree(destination)
        temporary.replace(destination)
    except Exception:
        shutil.rmtree(temporary, ignore_errors=True)
        raise
    return SavedDataset(manifest=manifest, frames=result.frames, directory=destination)


def load_simulation_dataset(
    cases_root: str | Path,
    case_id: str,
    dataset_id: str,
) -> SavedDataset:
    case_directory = resolve_case_path(cases_root, case_id)
    directory = case_directory / "datasets" / _validate_dataset_id(dataset_id)
    manifest = DatasetManifest.model_validate_json(
        (directory / "manifest.json").read_text(encoding="utf-8")
    )
    table = pd.read_parquet(directory / "ground_truth.parquet", engine="pyarrow")
    frames = []
    for timestamp_s, group in table.groupby("timestamp_s", sort=True):
        states = []
        for row in group.itertuples(index=False):
            velocity = None
            if row.velocity_x_mps is not None and row.velocity_y_mps is not None:
                velocity = Velocity2D(
                    x_mps=float(row.velocity_x_mps), y_mps=float(row.velocity_y_mps)
                )
            states.append(
                GroundTruthState(
                    timestamp_s=float(row.timestamp_s),
                    truth_id=row.truth_id,
                    group_truth_id=(None if pd.isna(row.group_truth_id) else row.group_truth_id),
                    is_group_leader=bool(row.is_group_leader),
                    position=Position3D(
                        x_m=float(row.x_m), y_m=float(row.y_m), z_m=float(row.z_m)
                    ),
                    velocity=velocity,
                    age_class=AgeClass(row.age_class),
                )
            )
        frames.append(GroundTruthFrame(timestamp_s=float(timestamp_s), states=tuple(states)))
    return SavedDataset(manifest=manifest, frames=tuple(frames), directory=directory)


def run_and_save_simulation(
    cases_root: str | Path,
    config: SimulationConfig,
    *,
    overwrite: bool = False,
) -> SavedDataset:
    environment_case = load_case(cases_root, config.case_id)
    return save_simulation_dataset(
        cases_root,
        simulate(environment_case, config),
        overwrite=overwrite,
    )
