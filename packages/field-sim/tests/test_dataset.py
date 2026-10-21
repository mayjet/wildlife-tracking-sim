from __future__ import annotations

from shepherd_contracts import Position2D, Velocity2D

from field_sim import (
    LinearMotion,
    SimulationConfig,
    load_simulation_dataset,
    run_and_save_simulation,
)


def test_dataset_manifest_parquet_round_trip_and_reproducibility(saved_case) -> None:
    cases_root, environment_case = saved_case
    config = SimulationConfig(
        case_id=environment_case.case_spec.case_id,
        dataset_id="straight-001",
        seed=9,
        duration_s=5.0,
        step_s=1.0,
        motion=LinearMotion(
            kind="linear",
            start=Position2D(x_m=-10.0, y_m=-5.0),
            velocity=Velocity2D(x_mps=1.0, y_mps=0.5),
        ),
    )
    first = run_and_save_simulation(cases_root, config)
    loaded = load_simulation_dataset(cases_root, config.case_id, config.dataset_id)
    assert loaded.frames == first.frames
    assert loaded.manifest == first.manifest
    assert (first.directory / "manifest.json").is_file()
    assert (first.directory / "ground_truth.parquet").is_file()
    assert loaded.manifest.scenario_config["observation_data_status"] == "not_generated_phase6"

    second_config = config.model_copy(update={"dataset_id": "straight-002"})
    second = run_and_save_simulation(cases_root, second_config)
    assert second.frames == first.frames


def test_dataset_is_not_overwritten_implicitly(saved_case) -> None:
    cases_root, environment_case = saved_case
    config = SimulationConfig(
        case_id=environment_case.case_spec.case_id,
        dataset_id="stationary",
        duration_s=1.0,
        step_s=1.0,
        motion={"kind": "stationary", "position": {"x_m": 0.0, "y_m": 0.0}},
    )
    run_and_save_simulation(cases_root, config)
    try:
        run_and_save_simulation(cases_root, config)
    except FileExistsError:
        pass
    else:
        raise AssertionError("existing Dataset was overwritten")
