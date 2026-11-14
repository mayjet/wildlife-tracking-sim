from __future__ import annotations

from field_campost import PlacementDefinition, generate_placement_layout


def test_declarative_grid_and_uniform_match_point_count(environment_case):
    grid_definition = PlacementDefinition(
        layout_id="grid-10m-cam4-v1",
        method="grid",
        mount={"camera_count": 4},
        parameters={"spacing_m": 10.0},
    )
    uniform_definition = PlacementDefinition(
        layout_id="uniform-cam4-v1",
        method="uniform",
        mount={"camera_count": 4},
        parameters={
            "point_count": "match_grid40",
            "reference_grid_spacing_m": 10.0,
        },
    )

    grid = generate_placement_layout(environment_case, grid_definition)
    uniform = generate_placement_layout(environment_case, uniform_definition)

    assert len(grid.points) == len(uniform.points)
    assert len(grid.camera_layout.cameras) == len(grid.points) * 4
    assert len(uniform.camera_layout.cameras) == len(uniform.points) * 4
    assert grid.metadata["generator"] == "grid"
    assert uniform.metadata["generator"] == "uniform"


def test_generic_grid_uses_declared_spacing(environment_case):
    definition = PlacementDefinition(
        layout_id="grid-25m-cam6-v1",
        method="grid",
        parameters={"spacing_m": 25.0},
    )

    layout = generate_placement_layout(environment_case, definition)

    assert layout.metadata["parameters"]["spacing_m"] == 25.0


def test_grid40_rejects_spacing_override(environment_case):
    definition = PlacementDefinition(
        layout_id="invalid-grid40-v1",
        method="grid40",
        parameters={"spacing_m": 20.0},
    )

    import pytest

    with pytest.raises(ValueError, match="fixed at 40 m"):
        generate_placement_layout(environment_case, definition)


def test_declarative_camera_mount_uses_degrees(environment_case):
    definition = PlacementDefinition(
        layout_id="grid-camera-angle-v1",
        method="grid",
        mount={"camera_count": 3, "horizontal_fov_deg": 90.0},
        parameters={"spacing_m": 20.0},
    )

    layout = generate_placement_layout(environment_case, definition)

    assert len(layout.points[0].camera_ids) == 3
    assert layout.camera_layout.cameras[0].horizontal_fov_rad > 1.5
