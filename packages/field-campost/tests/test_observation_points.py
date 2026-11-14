from __future__ import annotations

from math import pi

import numpy as np
import pytest
from field_environment import save_case

from field_campost import (
    CameraMountProfile,
    create_default_observation_point_layouts,
    create_observation_point_layout,
    generate_grid_observation_points,
    load_observation_point_layout,
    save_observation_point_layout,
)


def test_grid_and_uniform_layouts_have_equal_point_counts(environment_case):
    profile = CameraMountProfile(profile_id="pole5m-cam6", camera_count=6)
    grid, uniform = create_default_observation_point_layouts(
        environment_case, profile, grid_spacing_m=10.0
    )

    assert len(grid.points) == len(uniform.points)
    assert len(grid.camera_layout.cameras) == len(grid.points) * 6
    assert all(len(point.camera_ids) == 6 for point in uniform.points)


def test_camera_count_resolves_even_yaw_and_downward_pitch(environment_case):
    placements = generate_grid_observation_points(environment_case, spacing_m=20.0)
    profile = CameraMountProfile(profile_id="pole5m-cam3", camera_count=3)
    layout = create_observation_point_layout(
        environment_case,
        placements[:1],
        profile,
        layout_id="three-camera-layout",
        placement_method="test",
    )

    yaws = [camera.orientation.yaw_rad for camera in layout.camera_layout.cameras]
    assert np.allclose(yaws, (0.0, 2.0 * pi / 3.0, -2.0 * pi / 3.0))
    assert all(camera.orientation.pitch_rad > 0.0 for camera in layout.camera_layout.cameras)
    assert layout.points[0].position.z_m > environment_case.heightmap.surface_elevation_at(
        layout.points[0].position.x_m, layout.points[0].position.y_m
    )


def test_observation_point_layout_round_trip(tmp_path, environment_case):
    cases_root = tmp_path / "cases"
    save_case(environment_case, cases_root)
    profile = CameraMountProfile(profile_id="pole5m-cam6", camera_count=6)
    layout, _ = create_default_observation_point_layouts(
        environment_case, profile, grid_spacing_m=10.0
    )

    path = save_observation_point_layout(cases_root, environment_case.case_spec.case_id, layout)

    assert load_observation_point_layout(
        cases_root, environment_case.case_spec.case_id, layout.layout_id
    ) == layout
    assert path.name == "layout.json"
    assert (path.parent / "generation.json").is_file()
    with pytest.raises(FileExistsError):
        save_observation_point_layout(cases_root, environment_case.case_spec.case_id, layout)
