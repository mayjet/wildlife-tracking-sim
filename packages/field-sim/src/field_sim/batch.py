from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from field_campost import (
    generate_placement_layout,
    load_observation_point_layout,
    load_placement_definition,
    save_observation_point_layout,
)
from field_environment import load_case, resolve_case_path

from .dataset import (
    load_simulation_dataset,
    run_and_save_simulation,
    save_observations_for_layout,
)
from .experiment import LoadedExperimentPlan, save_experiment_snapshot
from .observations import VisibilityConfig
from .route_generators import generate_resolved_route, load_route_inputs
from .routes import route_to_simulation_config, save_resolved_route


@dataclass(frozen=True)
class ExperimentBatchResult:
    experiment_directory: Path
    statuses: dict[str, str]


def run_experiment_plan(
    cases_root: str | Path,
    loaded: LoadedExperimentPlan,
    *,
    overwrite: bool = False,
) -> ExperimentBatchResult:
    environment_case = load_case(cases_root, loaded.plan.case_id)
    placement_cache = {}
    route_cache = {}
    statuses = {}
    visibility = VisibilityConfig(
        deer_height_m=loaded.plan.visibility.deer_height_m,
        sample_heights_m=loaded.plan.visibility.sample_heights_m,
        observation_rule="full_body",
    )
    for combination in loaded.combinations:
        try:
            placement_key = str(combination.layout_definition_path)
            if placement_key not in placement_cache:
                definition, _ = load_placement_definition(
                    combination.layout_definition_path
                )
                generated = generate_placement_layout(environment_case, definition)
                layout_path = (
                    resolve_case_path(cases_root, loaded.plan.case_id)
                    / "observation_point_layouts"
                    / generated.layout_id
                    / "layout.json"
                )
                if layout_path.exists() and not overwrite:
                    stored = load_observation_point_layout(
                        cases_root, loaded.plan.case_id, generated.layout_id
                    )
                    if stored != generated:
                        raise ValueError(
                            f"stored layout differs from declaration: {generated.layout_id}"
                        )
                    layout = stored
                else:
                    save_observation_point_layout(
                        cases_root,
                        loaded.plan.case_id,
                        generated,
                        overwrite=overwrite,
                    )
                    layout = generated
                placement_cache[placement_key] = layout
            layout = placement_cache[placement_key]

            route_key = str(combination.route_definition_path)
            if route_key not in route_cache:
                definition, waypoint_set, _ = load_route_inputs(
                    combination.route_definition_path
                )
                route = generate_resolved_route(
                    environment_case, definition, waypoint_set
                )
                route_directory = (
                    resolve_case_path(cases_root, loaded.plan.case_id)
                    / "routes"
                    / definition.route_group_id
                    / "variants"
                    / definition.route_id
                )
                if not route_directory.exists() or overwrite:
                    save_resolved_route(cases_root, route, overwrite=overwrite)
                route_cache[route_key] = route
            route = route_cache[route_key]

            dataset_id = f"{route.definition.route_id}-seed{combination.seed}"
            config = route_to_simulation_config(
                route,
                dataset_id=dataset_id,
                speed_mps=loaded.plan.simulation.speed_mps,
                step_s=loaded.plan.simulation.step_s,
                truth_id=loaded.plan.simulation.truth_id,
                age_class=loaded.plan.simulation.age_class,
                seed=combination.seed,
            )
            dataset_directory = (
                resolve_case_path(cases_root, loaded.plan.case_id)
                / "datasets"
                / dataset_id
            )
            if dataset_directory.exists() and not overwrite:
                load_simulation_dataset(cases_root, loaded.plan.case_id, dataset_id)
            else:
                run_and_save_simulation(cases_root, config, overwrite=overwrite)
            observation_directory = (
                dataset_directory / "observations" / layout.layout_id
            )
            if not observation_directory.exists() or overwrite:
                save_observations_for_layout(
                    cases_root,
                    loaded.plan.case_id,
                    dataset_id,
                    layout,
                    visibility,
                    overwrite=overwrite,
                )
            statuses[combination.combination_id] = "completed"
        except Exception as error:
            statuses[combination.combination_id] = f"failed: {type(error).__name__}: {error}"
    experiment_directory = (
        resolve_case_path(cases_root, loaded.plan.case_id)
        / "experiments"
        / loaded.plan.experiment_id
    )
    if experiment_directory.exists():
        (experiment_directory / "status.json").write_text(
            json.dumps(statuses, ensure_ascii=False, indent=2), encoding="utf-8"
        )
    else:
        save_experiment_snapshot(cases_root, loaded, statuses)
    return ExperimentBatchResult(
        experiment_directory=experiment_directory,
        statuses=statuses,
    )
