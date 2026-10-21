from __future__ import annotations

import sys
from pathlib import Path

import pytest
from shepherd_contracts import CameraOrientation

REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
for source_root in (
    REPOSITORY_ROOT / "libs" / "shepherd-contracts" / "src",
    REPOSITORY_ROOT / "packages" / "field-environment" / "src",
    REPOSITORY_ROOT / "packages" / "field-campost" / "src",
):
    sys.path.insert(0, str(source_root))

from field_campost import FixedCameraPlacement, create_fixed_camera_layout
from field_environment import FarmBoundary, TerrainGridSpec, create_synthetic_case


@pytest.fixture
def environment_case():
    case_id = "phase3-test"
    grid = TerrainGridSpec.from_extent(width_m=40.0, height_m=30.0, cell_size_m=10.0)
    boundary = FarmBoundary.rectangle(
        min_x_m=5.0,
        min_y_m=5.0,
        max_x_m=35.0,
        max_y_m=25.0,
        coordinate_system_name=f"{case_id}-local-enu",
    )
    return create_synthetic_case(
        case_id=case_id,
        terrain_kind="ridge",
        grid=grid,
        farm_boundary=boundary,
        generation_parameters={
            "base_elevation_m": 2.0,
            "height_m": 8.0,
            "width_m": 12.0,
            "angle_rad": 0.3,
        },
        seed=17,
    )


@pytest.fixture
def camera_layout(environment_case):
    placements = (
        FixedCameraPlacement(
            camera_id="north-west",
            x_m=5.0,
            y_m=25.0,
            height_above_ground_m=3.0,
            orientation=CameraOrientation(yaw_rad=-0.4, pitch_rad=0.2, roll_rad=0.0),
            horizontal_fov_rad=1.2,
            vertical_fov_rad=0.8,
            observation_interval_s=2.0,
        ),
        FixedCameraPlacement(
            camera_id="east",
            x_m=35.0,
            y_m=15.0,
            height_above_ground_m=4.0,
            orientation=CameraOrientation(yaw_rad=2.5, pitch_rad=0.1, roll_rad=0.05),
            horizontal_fov_rad=1.0,
            vertical_fov_rad=0.7,
        ),
    )
    return create_fixed_camera_layout(
        environment_case.heightmap, placements, layout_id="fixed-layout"
    )
