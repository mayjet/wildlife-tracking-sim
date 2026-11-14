from __future__ import annotations

from math import atan2, pi

import pandas as pd
from shepherd_contracts import (
    CameraLayout,
    CameraOrientation,
    CameraSpec,
    ObservationPointLayout,
    ObservationPointSpec,
    Position3D,
    Velocity2D,
)

from field_sim import (
    LinearMotion,
    SimulationConfig,
    VisibilityConfig,
    load_simulation_dataset,
    run_and_save_observation_dataset,
)


def test_phase7_dataset_round_trip_has_no_truth_columns_in_observations(saved_case):
    cases_root, environment_case = saved_case
    x_m, y_m = -10.0, 0.0
    position = Position3D(
        x_m=x_m,
        y_m=y_m,
        z_m=environment_case.heightmap.surface_elevation_at(x_m, y_m) + 5.0,
    )
    camera = CameraSpec(
        camera_id="point-001-cam-01",
        position=position,
        orientation=CameraOrientation(
            yaw_rad=0.0,
            pitch_rad=atan2(5.0 - 0.75, 20.0),
            roll_rad=0.0,
        ),
        horizontal_fov_rad=pi / 3.0,
        vertical_fov_rad=pi / 3.0,
        max_observation_distance_m=42.0,
        observation_interval_s=1.0,
    )
    layout = ObservationPointLayout(
        layout_id="dataset-layout",
        points=(
            ObservationPointSpec(
                point_id="point-001", position=position, camera_ids=(camera.camera_id,)
            ),
        ),
        camera_layout=CameraLayout(layout_id="dataset-cameras", cameras=(camera,)),
    )
    config = SimulationConfig(
        case_id=environment_case.case_spec.case_id,
        dataset_id="phase7-visible",
        duration_s=2.0,
        step_s=1.0,
        motion=LinearMotion(
            kind="linear",
            start={"x_m": 8.0, "y_m": 0.0},
            velocity=Velocity2D(x_mps=1.0, y_mps=0.0),
        ),
    )

    saved = run_and_save_observation_dataset(
        cases_root, config, layout, VisibilityConfig()
    )
    loaded = load_simulation_dataset(cases_root, config.case_id, config.dataset_id)
    table = pd.read_parquet(saved.directory / "observations.parquet")

    assert loaded.observation_frames == saved.observation_frames
    assert len(loaded.observation_frames) == len(loaded.frames)
    assert "truth_id" not in table.columns
    assert "group_truth_id" not in table.columns
    assert loaded.manifest.scenario_config["observation_data_status"] == "generated_phase7"
