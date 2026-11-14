from __future__ import annotations

from field_campost import (
    CameraMountProfile,
    GenesisRouteOverlay,
    GenesisScene,
    GenesisValidationRay,
    GenesisVisibilityOverlay,
    create_observation_point_layout,
    draw_genesis_experiment_overlays,
    generate_grid_observation_points,
    write_observation_infrastructure_assets,
)
import numpy as np


class _DebugScene:
    def __init__(self):
        self.calls = []

    def __getattr__(self, name):
        if not name.startswith("draw_debug_"):
            raise AttributeError(name)

        def record(*args, **kwargs):
            self.calls.append((name, args, kwargs))

        return record


def _layout(environment_case):
    placement = generate_grid_observation_points(
        environment_case, spacing_m=20.0
    )[:1]
    return create_observation_point_layout(
        environment_case,
        placement,
        CameraMountProfile(profile_id="test-cam3", camera_count=3),
        layout_id="genesis-test-layout",
        placement_method="test",
    )


def test_infrastructure_assets_keep_optical_contract(tmp_path, environment_case):
    layout = _layout(environment_case)

    assets = write_observation_infrastructure_assets(layout, tmp_path)

    assert assets.poles.is_file()
    assert assets.camera_housings.is_file()
    assert assets.infrastructure_usda.is_file()
    assert "CameraSpec optical frames" in assets.infrastructure_usda.read_text()
    assert assets.camera_housings.read_text().count("\nv ") == len(
        layout.camera_layout.cameras
    ) * 8


def test_debug_overlays_are_separate_from_physical_entities(environment_case):
    layout = _layout(environment_case)
    debug_scene = _DebugScene()
    genesis_scene = GenesisScene(debug_scene, (), None, "cpu")
    route = GenesisRouteOverlay(
        route_id="route",
        positions=np.asarray(((0.0, 0.0, 1.0), (1.0, 1.0, 1.0))),
        waypoints=np.asarray(((0.0, 0.0, 1.0),)),
    )
    visibility = GenesisVisibilityOverlay(
        visible_positions=np.asarray(((0.0, 0.0, 0.1),)),
        hidden_positions=np.asarray(((1.0, 1.0, 0.1),)),
    )
    ray = GenesisValidationRay(
        start=(0.0, 0.0, 5.0),
        end=(1.0, 1.0, 1.5),
        visible=False,
        reason="FOREST_OCCLUSION",
    )

    draw_genesis_experiment_overlays(
        genesis_scene,
        layout,
        selected_point_id=layout.points[0].point_id,
        show_fov=True,
        visibility=visibility,
        routes=(route,),
        rays=(ray,),
    )

    names = [call[0] for call in debug_scene.calls]
    assert names.count("draw_debug_mesh") >= 1
    assert "draw_debug_trajectory" in names
    assert names.count("draw_debug_points") == 2
    assert "draw_debug_sphere" in names
    assert "draw_debug_arrow" in names
    assert "draw_debug_line" in names
    frustum_meshes = [call[1][0] for call in debug_scene.calls if call[0] == "draw_debug_mesh"]
    assert sum(len(mesh.faces) for mesh in frustum_meshes) == len(
        layout.camera_layout.cameras
    ) * 6
