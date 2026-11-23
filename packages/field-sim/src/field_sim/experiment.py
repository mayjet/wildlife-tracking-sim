from __future__ import annotations

import json
from dataclasses import dataclass
from itertools import product
from pathlib import Path

import pandas as pd
import yaml
from pydantic import BaseModel, ConfigDict, Field, model_validator

from field_environment import resolve_repository_path, validate_case_id

from .herd_config import HerdProfile
from .observations import ObservationPositionErrorConfig


class ExperimentVisibility(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, allow_inf_nan=False)

    preview_cell_size_m: float = Field(default=40.0, gt=0.0)
    intermediate_cell_size_m: float = Field(default=10.0, gt=0.0)
    evaluation_cell_size_m: float = Field(default=1.0, gt=0.0)
    deer_height_m: float = Field(default=1.5, gt=0.0)
    sample_heights_m: tuple[float, ...] = (0.0, 0.75, 1.5)
    observation_position_error: ObservationPositionErrorConfig = (
        ObservationPositionErrorConfig()
    )


class ExperimentSimulation(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, allow_inf_nan=False)

    speed_mps: float = Field(default=1.5, gt=0.0)
    step_s: float = Field(default=1.0, gt=0.0)
    truth_id: str = Field(default="deer-001", min_length=1)
    age_class: str = "UNKNOWN"


class ExperimentMatrix(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    mode: str = "cartesian"

    @model_validator(mode="after")
    def validate_mode(self) -> "ExperimentMatrix":
        if self.mode != "cartesian":
            raise ValueError("only cartesian experiment matrices are supported")
        return self


class ExperimentPlan(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    experiment_id: str = Field(min_length=1)
    case_id: str = Field(min_length=1)
    placements: tuple[str, ...] = Field(min_length=1)
    routes: tuple[str, ...] = Field(min_length=1)
    seeds: tuple[int, ...] = (42,)
    matrix: ExperimentMatrix = ExperimentMatrix()
    visibility: ExperimentVisibility = ExperimentVisibility()
    simulation: ExperimentSimulation = ExperimentSimulation()
    herd_profiles: tuple[HerdProfile, ...] = ()
    include_single_individual: bool = True
    tracker_methods: tuple[str, ...] = ("last_observation", "constant_velocity")
    tracker_seed: int = 42

    @model_validator(mode="after")
    def validate_ids(self) -> "ExperimentPlan":
        validate_case_id(self.experiment_id)
        validate_case_id(self.case_id)
        if not self.seeds:
            raise ValueError("at least one seed is required")
        if not self.tracker_methods or any(not item for item in self.tracker_methods):
            raise ValueError("at least one tracker method is required")
        return self


@dataclass(frozen=True)
class ExperimentCombination:
    combination_id: str
    layout_definition_path: Path
    route_definition_path: Path
    seed: int
    herd_profile_id: str | None = None


@dataclass(frozen=True)
class LoadedExperimentPlan:
    plan: ExperimentPlan
    path: Path
    combinations: tuple[ExperimentCombination, ...]

    def dataframe(self) -> pd.DataFrame:
        return pd.DataFrame(
            [
                {
                    "combination_id": combination.combination_id,
                    "placement_file": str(combination.layout_definition_path),
                    "route_file": str(combination.route_definition_path),
                    "seed": combination.seed,
                    "herd_profile_id": combination.herd_profile_id,
                }
                for combination in self.combinations
            ]
        )


def load_experiment_plan(
    path: str | Path,
    *,
    start: str | Path | None = None,
) -> LoadedExperimentPlan:
    resolved = resolve_repository_path(path, start=start)
    if not resolved.is_file():
        raise FileNotFoundError(f"experiment plan not found: {resolved}")
    raw = yaml.safe_load(resolved.read_text(encoding="utf-8"))
    plan = ExperimentPlan.model_validate(raw)
    placement_paths = tuple((resolved.parent / path).resolve() for path in plan.placements)
    route_paths = tuple((resolved.parent / path).resolve() for path in plan.routes)
    missing = [path for path in (*placement_paths, *route_paths) if not path.is_file()]
    if missing:
        raise FileNotFoundError(f"experiment references missing files: {missing}")
    combinations = []
    profiles: tuple[HerdProfile | None, ...] = (
        ((None,) if plan.include_single_individual else ()) + plan.herd_profiles
    )
    if not profiles:
        raise ValueError("experiment requires a single individual or at least one herd profile")
    for placement_path, route_path, seed, profile in product(
        placement_paths, route_paths, plan.seeds, profiles
    ):
        combination_id = (
            f"{placement_path.stem}__{route_path.stem}__"
            f"{profile.profile_id + '__' if profile is not None else ''}seed{seed}"
        )
        validate_case_id(combination_id)
        combinations.append(
            ExperimentCombination(
                combination_id=combination_id,
                layout_definition_path=placement_path,
                route_definition_path=route_path,
                seed=seed,
                herd_profile_id=None if profile is None else profile.profile_id,
            )
        )
    return LoadedExperimentPlan(plan=plan, path=resolved, combinations=tuple(combinations))


def save_experiment_snapshot(
    cases_root: str | Path,
    loaded: LoadedExperimentPlan,
    statuses: dict[str, str],
    *,
    overwrite: bool = False,
) -> Path:
    from field_environment import resolve_case_path

    destination = (
        resolve_case_path(cases_root, loaded.plan.case_id)
        / "experiments"
        / loaded.plan.experiment_id
    )
    if destination.exists() and not overwrite:
        raise FileExistsError(f"Experiment snapshot already exists: {destination}")
    destination.mkdir(parents=True, exist_ok=True)
    (destination / "plan.json").write_text(
        loaded.plan.model_dump_json(indent=2), encoding="utf-8"
    )
    loaded.dataframe().to_csv(destination / "matrix.csv", index=False)
    (destination / "status.json").write_text(
        json.dumps(statuses, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return destination
