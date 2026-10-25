from dataclasses import replace

import pytest

from field_environment import (
    FarmBoundary,
    SceneConfig,
    SceneCropConfig,
    apply_scene_config,
    crop_heightmap,
    scene_crop_geometry,
)


def test_square_scene_crop_is_scaled_snapped_and_persistable(environment_case):
    environment_case = replace(
        environment_case,
        farm_boundary=FarmBoundary.rectangle(
            min_x_m=60.0,
            min_y_m=40.0,
            max_x_m=140.0,
            max_y_m=80.0,
            coordinate_system_name=environment_case.case_spec.coordinate_system.name,
        ),
    )
    configured = apply_scene_config(
        environment_case,
        SceneConfig(
            forest_height_m=10.0,
            crop=SceneCropConfig(shape="square", scale=1.5, minimum_margin_m=10.0),
        ),
    )

    geometry = scene_crop_geometry(configured)
    min_x, min_y, max_x, max_y = geometry.bounds
    assert max_x - min_x == pytest.approx(max_y - min_y)
    assert configured.forest is None or configured.forest.assumed_height_m == 10.0
    cropped = crop_heightmap(configured.heightmap, geometry)
    assert cropped.width_m == pytest.approx(max_x - min_x)
    assert cropped.height_m == pytest.approx(max_y - min_y)


def test_scene_crop_outside_terrain_is_rejected(environment_case):
    with pytest.raises(ValueError, match="outside"):
        apply_scene_config(
            environment_case,
            SceneConfig(
                crop=SceneCropConfig(
                    scale=1.0,
                    minimum_margin_m=0.0,
                    center_offset_x_m=100000.0,
                )
            ),
        )
