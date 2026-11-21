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
    Observation,
    ObservationFrame,
    ObservationPointLayout,
    Position2D,
    Position3D,
    Velocity2D,
)

from field_environment import load_case, resolve_case_path, validate_case_id

from .config import SimulationConfig
from .herd_config import HerdSimulationConfig
from .herd_simulator import simulate_herd
from .routes import ResolvedRoute
from .simulator import SimulationResult, simulate
from .observations import (
    ObservationPositionErrorConfig,
    ObservationResult,
    VisibilityConfig,
    generate_observations,
)


@dataclass(frozen=True)
class SavedDataset:
    manifest: DatasetManifest
    frames: tuple[GroundTruthFrame, ...]
    directory: Path
    observation_frames: tuple[ObservationFrame, ...] = ()


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


def _observations_to_dataframe(frames: tuple[ObservationFrame, ...]) -> pd.DataFrame:
    rows = []
    for frame in frames:
        for observation in frame.observations:
            rows.append(
                {
                    "timestamp_s": observation.timestamp_s,
                    "camera_id": observation.camera_id,
                    "observation_id": observation.observation_id,
                    "x_m": observation.position.x_m,
                    "y_m": observation.position.y_m,
                    "age_class": observation.age_class.value,
                }
            )
    return pd.DataFrame(
        rows,
        columns=(
            "timestamp_s",
            "camera_id",
            "observation_id",
            "x_m",
            "y_m",
            "age_class",
        ),
    )


def _scenario_config(result: SimulationResult, *, observation_status: str) -> dict:
    config = result.config
    common = {
        "individual_count": len(result.frames[0].states) if result.frames else 0,
        "surface_interpolation": "piecewise triangular, matching TerrainMesh faces",
        "surface_following": {
            "enabled": True,
            "method": "heightmap_piecewise_triangular",
            "ground_truth_clearance_m": 0.0,
            "simulator_actor_foot_clearance_m": 0.03,
            "simulator_surface_tolerance_m": 0.05,
        },
        "observation_data_status": observation_status,
    }
    if isinstance(config, HerdSimulationConfig):
        common.update(
            {
                "herd_count": 1,
                "herd_id": config.herd_id,
                "herd_profile_id": config.profile.profile_id,
                "adult_count": config.profile.adult_count,
                "juvenile_count": config.profile.juvenile_count,
                "route_id": config.route_id,
                "speed_mps": config.speed_mps,
                "avoidance": {
                    "local_angles_deg": list(config.local_avoidance_angles_deg),
                    "local_radius_m": config.local_avoidance_radius_m,
                    "astar_lookahead_m": config.astar_lookahead_m,
                },
            }
        )
    else:
        common.update(
            {
                "truth_id": config.truth_id,
                "motion": config.motion.model_dump(mode="json"),
                "age_class": config.age_class.value,
            }
        )
    return common


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
        duration_s=result.duration_s,
        simulation_step_s=result.config.step_s,
        scenario_config={
            "case_sha256": _case_hash(case_directory),
            **_scenario_config(result, observation_status="not_generated_phase6"),
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
    observation_frames = []
    observation_path = directory / "observations.parquet"
    if observation_path.is_file():
        observation_table = pd.read_parquet(observation_path, engine="pyarrow")
        grouped = {
            float(timestamp_s): group
            for timestamp_s, group in observation_table.groupby("timestamp_s", sort=True)
        }
        for frame in frames:
            observations = []
            group = grouped.get(frame.timestamp_s)
            if group is not None:
                for row in group.itertuples(index=False):
                    observations.append(
                        Observation(
                            timestamp_s=float(row.timestamp_s),
                            camera_id=row.camera_id,
                            observation_id=row.observation_id,
                            position=Position2D(x_m=float(row.x_m), y_m=float(row.y_m)),
                            age_class=AgeClass(row.age_class),
                        )
                    )
            observation_frames.append(
                ObservationFrame(
                    timestamp_s=frame.timestamp_s,
                    observations=tuple(observations),
                )
            )
    return SavedDataset(
        manifest=manifest,
        frames=tuple(frames),
        directory=directory,
        observation_frames=tuple(observation_frames),
    )


def save_observation_dataset(
    cases_root: str | Path,
    simulation_result: SimulationResult,
    observation_result: ObservationResult,
    *,
    overwrite: bool = False,
) -> SavedDataset:
    case_directory = resolve_case_path(cases_root, simulation_result.config.case_id)
    dataset_id = _validate_dataset_id(simulation_result.config.dataset_id)
    destination = case_directory / "datasets" / dataset_id
    if destination.exists() and not overwrite:
        raise FileExistsError(f"Dataset already exists: {destination}")
    ground_truth_ref = f"datasets/{dataset_id}/ground_truth.parquet"
    observation_ref = f"datasets/{dataset_id}/observations.parquet"
    manifest = DatasetManifest(
        schema_version="1.0",
        case_id=simulation_result.config.case_id,
        dataset_id=dataset_id,
        seed=simulation_result.config.seed,
        duration_s=simulation_result.duration_s,
        simulation_step_s=simulation_result.config.step_s,
        scenario_config={
            "case_sha256": _case_hash(case_directory),
            **_scenario_config(simulation_result, observation_status="generated_phase7"),
            "observation_point_layout_id": observation_result.layout.layout_id,
            "visibility": observation_result.config.model_dump(mode="json"),
            "observation_position_error": observation_result.position_error_config.model_dump(
                mode="json"
            ),
        },
        observation_data_ref=observation_ref,
        ground_truth_data_ref=ground_truth_ref,
    )
    temporary = destination.parent / f".{dataset_id}.tmp-{uuid4().hex}"
    temporary.mkdir()
    try:
        _frames_to_dataframe(simulation_result.frames).to_parquet(
            temporary / "ground_truth.parquet", index=False, engine="pyarrow"
        )
        _observations_to_dataframe(observation_result.frames).to_parquet(
            temporary / "observations.parquet", index=False, engine="pyarrow"
        )
        (temporary / "manifest.json").write_text(
            manifest.model_dump_json(indent=2), encoding="utf-8"
        )
        (temporary / "simulation_config.json").write_text(
            simulation_result.config.model_dump_json(indent=2), encoding="utf-8"
        )
        (temporary / "visibility_config.json").write_text(
            observation_result.config.model_dump_json(indent=2), encoding="utf-8"
        )
        (temporary / "observation_position_error_config.json").write_text(
            observation_result.position_error_config.model_dump_json(indent=2),
            encoding="utf-8",
        )
        (temporary / "observation_point_layout.json").write_text(
            observation_result.layout.model_dump_json(indent=2), encoding="utf-8"
        )
        if destination.exists():
            shutil.rmtree(destination)
        temporary.replace(destination)
    except Exception:
        shutil.rmtree(temporary, ignore_errors=True)
        raise
    return SavedDataset(
        manifest=manifest,
        frames=simulation_result.frames,
        directory=destination,
        observation_frames=observation_result.frames,
    )


def run_and_save_observation_dataset(
    cases_root: str | Path,
    config: SimulationConfig,
    layout: ObservationPointLayout,
    visibility_config: VisibilityConfig | None = None,
    position_error_config: ObservationPositionErrorConfig | None = None,
    *,
    overwrite: bool = False,
) -> SavedDataset:
    environment_case = load_case(cases_root, config.case_id)
    simulation_result = simulate(environment_case, config)
    observation_result = generate_observations(
        environment_case,
        layout,
        simulation_result.frames,
        visibility_config,
        position_error_config,
    )
    return save_observation_dataset(
        cases_root,
        simulation_result,
        observation_result,
        overwrite=overwrite,
    )


def save_observations_for_layout(
    cases_root: str | Path,
    case_id: str,
    dataset_id: str,
    layout: ObservationPointLayout,
    visibility_config: VisibilityConfig | None = None,
    position_error_config: ObservationPositionErrorConfig | None = None,
    *,
    overwrite: bool = False,
) -> Path:
    """Add one layout-specific Observation table to a shared Ground Truth Dataset."""
    environment_case = load_case(cases_root, case_id)
    saved = load_simulation_dataset(cases_root, case_id, dataset_id)
    resolved_config = visibility_config or VisibilityConfig()
    resolved_error_config = position_error_config or ObservationPositionErrorConfig()
    observation_result = generate_observations(
        environment_case,
        layout,
        saved.frames,
        resolved_config,
        resolved_error_config,
    )
    observation_directory = saved.directory / "observations" / layout.layout_id
    if observation_directory.exists() and not overwrite:
        raise FileExistsError(f"Observation set already exists: {observation_directory}")
    temporary = observation_directory.parent / f".{layout.layout_id}.tmp-{uuid4().hex}"
    temporary.mkdir(parents=True, exist_ok=False)
    try:
        _observations_to_dataframe(observation_result.frames).to_parquet(
            temporary / "observations.parquet", index=False, engine="pyarrow"
        )
        (temporary / "visibility_config.json").write_text(
            resolved_config.model_dump_json(indent=2), encoding="utf-8"
        )
        (temporary / "observation_position_error_config.json").write_text(
            resolved_error_config.model_dump_json(indent=2), encoding="utf-8"
        )
        (temporary / "observation_point_layout.json").write_text(
            layout.model_dump_json(indent=2), encoding="utf-8"
        )
        manifest = {
            "schema_version": "1.0",
            "case_id": case_id,
            "dataset_id": dataset_id,
            "layout_id": layout.layout_id,
            "ground_truth_ref": "../../ground_truth.parquet",
            "observations_ref": "observations.parquet",
            "observation_count": sum(
                len(frame.observations) for frame in observation_result.frames
            ),
            "truth_fields_excluded": True,
            "observation_position_error": resolved_error_config.model_dump(mode="json"),
        }
        (temporary / "manifest.json").write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        if observation_directory.exists():
            shutil.rmtree(observation_directory)
        temporary.replace(observation_directory)
    except Exception:
        shutil.rmtree(temporary, ignore_errors=True)
        raise
    return observation_directory


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


def run_and_save_herd_simulation(
    cases_root: str | Path,
    route: ResolvedRoute,
    config: HerdSimulationConfig,
    *,
    overwrite: bool = False,
) -> SavedDataset:
    environment_case = load_case(cases_root, config.case_id)
    return save_simulation_dataset(
        cases_root,
        simulate_herd(environment_case, route, config),
        overwrite=overwrite,
    )
