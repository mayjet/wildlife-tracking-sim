from __future__ import annotations

from field_campost import (
    CameraMountProfile,
    GenesisDeerProxy,
    GenesisRouteOverlay,
    GenesisScene,
    GenesisValidationRay,
    GenesisVisibilityOverlay,
    build_genesis_deer_frame,
    create_genesis_deer_proxy,
    create_observation_point_layout,
    drape_genesis_route_overlay,
    draw_genesis_experiment_overlays,
    generate_grid_observation_points,
    write_observation_infrastructure_assets,
)
import numpy as np
import pytest
from shepherd_contracts import (
    GroundTruthFrame,
    GroundTruthState,
    Position3D,
    Velocity2D,
)


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


def test_route_overlay_and_deer_proxy_follow_the_common_surface(environment_case):
    route = drape_genesis_route_overlay(
        environment_case,
        route_id="surface-route",
        coordinates=np.asarray(((5.0, 5.0), (25.0, 20.0))),
        waypoints=np.asarray(((5.0, 5.0), (25.0, 20.0))),
        sample_spacing_m=0.25,
        height_above_surface_m=1.0,
    )
    segment_lengths = np.linalg.norm(np.diff(route.positions[:, :2], axis=0), axis=1)
    assert np.max(segment_lengths) <= 0.25 + 1.0e-9
    for x_m, y_m, z_m in route.positions:
        assert z_m == pytest.approx(
            environment_case.heightmap.surface_elevation_at(x_m, y_m) + 1.0
        )

    proxy = create_genesis_deer_proxy(
        environment_case, truth_id="deer-001", x_m=10.0, y_m=10.0
    )
    assert proxy.color[3] == 1.0
    assert proxy.foot_position[2] == pytest.approx(
        environment_case.heightmap.surface_elevation_at(10.0, 10.0) + 0.03
    )


def test_runtime_frame_forces_proxy_feet_to_surface(environment_case):
    frame = GroundTruthFrame(
        timestamp_s=2.0,
        states=(
            GroundTruthState(
                timestamp_s=2.0,
                truth_id="deer-001",
                position=Position3D(x_m=10.0, y_m=10.0, z_m=-100.0),
                velocity=Velocity2D(x_mps=0.0, y_mps=1.0),
            ),
        ),
    )

    runtime_frame = build_genesis_deer_frame(environment_case, frame)

    assert runtime_frame.maximum_surface_difference_m > 100.0
    proxy = runtime_frame.proxies[0]
    assert proxy.heading_rad == pytest.approx(np.pi / 2.0)
    assert proxy.foot_position[2] == pytest.approx(
        environment_case.heightmap.surface_elevation_at(10.0, 10.0) + 0.03
    )


def test_deer_proxy_is_drawn_as_opaque_closed_mesh(environment_case):
    layout = _layout(environment_case)
    debug_scene = _DebugScene()
    genesis_scene = GenesisScene(debug_scene, (), None, "cpu")
    proxy = GenesisDeerProxy(
        truth_id="deer-001", foot_position=(10.0, 10.0, 2.0)
    )

    draw_genesis_experiment_overlays(
        genesis_scene,
        layout,
        deer_proxies=(proxy,),
    )

    meshes = [call[1][0] for call in debug_scene.calls if call[0] == "draw_debug_mesh"]
    assert len(meshes) == 1
    assert len(meshes[0].faces) == 12
    assert np.all(meshes[0].visual.face_colors[:, 3] == 255)
