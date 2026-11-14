from __future__ import annotations

from dataclasses import replace
from math import atan2, pi

import numpy as np
from shapely.geometry import box, mapping
from shepherd_contracts import (
    CameraLayout,
    CameraOrientation,
    CameraSpec,
    GroundTruthFrame,
    GroundTruthState,
    ObservationPointLayout,
    ObservationPointSpec,
    Position3D,
)

from field_environment import FeatureLayerStatus, Heightmap, PolygonFeatureLayer
from field_sim import (
    AnalyticRaycastBackend,
    OcclusionKind,
    VisibilityClass,
    VisibilityConfig,
    compute_visibility_map,
    generate_observations,
    visibility_map_metrics,
)


def _single_point_layout(simulation_case, *, camera_count: int = 1):
    x_m, y_m = -10.0, 0.0
    ground_z_m = simulation_case.heightmap.surface_elevation_at(x_m, y_m)
    position = Position3D(x_m=x_m, y_m=y_m, z_m=ground_z_m + 5.0)
    cameras = []
    camera_ids = []
    for index in range(camera_count):
        camera_id = f"point-001-cam-{index + 1:02d}"
        camera_ids.append(camera_id)
        cameras.append(
            CameraSpec(
                camera_id=camera_id,
                position=position,
                orientation=CameraOrientation(
                    yaw_rad=(
                        0.0
                        if camera_count == 1
                        else (-pi / 6.0 if index == 0 else pi / 6.0)
                    ),
                    pitch_rad=atan2(5.0 - 0.75, 20.0),
                    roll_rad=0.0,
                ),
                horizontal_fov_rad=pi / 3.0,
                vertical_fov_rad=pi / 3.0,
                max_observation_distance_m=42.0,
                observation_interval_s=1.0,
            )
        )
    return ObservationPointLayout(
        layout_id="test-layout",
        points=(
            ObservationPointSpec(
                point_id="point-001",
                position=position,
                camera_ids=tuple(camera_ids),
            ),
        ),
        camera_layout=CameraLayout(layout_id="test-cameras", cameras=tuple(cameras)),
    )


def _state(simulation_case, x_m: float, y_m: float = 0.0):
    return GroundTruthState(
        timestamp_s=0.0,
        truth_id="secret-truth-id",
        position=Position3D(
            x_m=x_m,
            y_m=y_m,
            z_m=simulation_case.heightmap.surface_elevation_at(x_m, y_m),
        ),
    )


def _polygon_layer(simulation_case, layer_type: str, geometry, height_m: float):
    return PolygonFeatureLayer(
        layer_type=layer_type,
        status=FeatureLayerStatus.AVAILABLE,
        coordinate_system_name=simulation_case.case_spec.coordinate_system.name,
        features=(
            {
                "type": "Feature",
                "geometry": mapping(geometry),
                "properties": {"assumed_height_m": height_m},
            },
        ),
        source="test",
        assumed_height_m=height_m,
    )


def test_visible_deer_generates_truth_isolated_observation(simulation_case):
    layout = _single_point_layout(simulation_case)
    frame = GroundTruthFrame(timestamp_s=0.0, states=(_state(simulation_case, 10.0),))

    result = generate_observations(simulation_case, layout, (frame,))

    assert len(result.frames[0].observations) == 1
    observation = result.frames[0].observations[0]
    assert observation.position.x_m == 10.0
    assert "truth" not in observation.model_dump()
    assert "secret" not in observation.model_dump_json()


def test_observation_point_seam_is_deduplicated(simulation_case):
    layout = _single_point_layout(simulation_case, camera_count=2)
    frame = GroundTruthFrame(timestamp_s=0.0, states=(_state(simulation_case, 10.0),))

    result = generate_observations(simulation_case, layout, (frame,))

    assert len(result.frames[0].observations) == 1


def test_vertical_fov_creates_blind_area_below_pole(simulation_case):
    layout = _single_point_layout(simulation_case)
    frame = GroundTruthFrame(timestamp_s=0.0, states=(_state(simulation_case, -8.0),))

    result = generate_observations(simulation_case, layout, (frame,))

    assert result.frames[0].observations == ()


def test_forest_and_building_block_observation(simulation_case):
    layout = _single_point_layout(simulation_case)
    frame = GroundTruthFrame(timestamp_s=0.0, states=(_state(simulation_case, 10.0),))
    forest_case = replace(
        simulation_case,
        forest=_polygon_layer(simulation_case, "forest", box(8.0, -2.0, 12.0, 2.0), 10.0),
    )
    building_case = replace(
        simulation_case,
        buildings=_polygon_layer(simulation_case, "buildings", box(0.0, -2.0, 2.0, 2.0), 8.0),
    )

    assert generate_observations(forest_case, layout, (frame,)).frames[0].observations == ()
    assert generate_observations(building_case, layout, (frame,)).frames[0].observations == ()


def test_terrain_ridge_blocks_three_dimensional_ray(simulation_case):
    elevations = np.zeros_like(simulation_case.heightmap.values)
    elevations[:, 4:6] = 20.0
    terrain_case = replace(
        simulation_case,
        heightmap=Heightmap(values=elevations, grid=simulation_case.heightmap.grid),
    )
    raycast = AnalyticRaycastBackend(terrain_case, sample_step_m=0.5)

    hit = raycast.first_occlusion(
        np.asarray((-30.0, 0.0, 5.0)),
        np.asarray((30.0, 0.0, 1.5)),
    )

    assert hit.kind is OcclusionKind.TERRAIN


def test_empty_observation_frame_and_visibility_map(simulation_case):
    layout = _single_point_layout(simulation_case)
    frame = GroundTruthFrame(timestamp_s=0.0, states=(_state(simulation_case, 45.0),))

    result = generate_observations(simulation_case, layout, (frame,))
    visibility_map = compute_visibility_map(
        simulation_case,
        layout,
        VisibilityConfig(),
        cell_size_m=20.0,
    )

    assert result.frames[0].observations == ()
    assert visibility_map.classes.shape == (3, 3)
    assert set(visibility_map.classes.ravel()).issubset(set(VisibilityClass))
    assert visibility_map.failure_codes.shape == visibility_map.classes.shape


def test_visibility_map_checkpoint_resumes(tmp_path, simulation_case):
    layout = _single_point_layout(simulation_case)
    checkpoint = tmp_path / "visibility.npz"

    first = compute_visibility_map(
        simulation_case,
        layout,
        VisibilityConfig(),
        cell_size_m=10.0,
        checkpoint_path=checkpoint,
        checkpoint_row_count=1,
    )
    second = compute_visibility_map(
        simulation_case,
        layout,
        VisibilityConfig(),
        cell_size_m=10.0,
        checkpoint_path=checkpoint,
        checkpoint_row_count=1,
    )

    assert checkpoint.is_file()
    assert np.array_equal(first.classes, second.classes)
    assert np.array_equal(first.failure_codes, second.failure_codes)
    metrics = visibility_map_metrics(second)
    assert metrics["evaluated_cell_count"] > 0
    assert sum(metrics["class_counts"].values()) == metrics["evaluated_cell_count"]


def test_parallel_binary_visibility_matches_detailed_full_visibility(
    tmp_path, simulation_case
):
    layout = _single_point_layout(simulation_case)
    detailed = compute_visibility_map(
        simulation_case,
        layout,
        VisibilityConfig(),
        cell_size_m=10.0,
    )
    binary = compute_visibility_map(
        simulation_case,
        layout,
        VisibilityConfig(),
        cell_size_m=10.0,
        checkpoint_path=tmp_path / "binary-visibility.npz",
        checkpoint_row_count=2,
        worker_count=2,
        binary_only=True,
    )

    assert np.array_equal(
        detailed.classes == VisibilityClass.FULLY_VISIBLE,
        binary.classes == VisibilityClass.FULLY_VISIBLE,
    )
    assert set(binary.classes.ravel()).issubset(
        {
            VisibilityClass.OUTSIDE_AREA,
            VisibilityClass.NOT_VISIBLE,
            VisibilityClass.FULLY_VISIBLE,
        }
    )
