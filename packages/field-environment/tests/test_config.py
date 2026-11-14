from __future__ import annotations

from pathlib import Path

import pytest

from field_environment import (
    CaseMode,
    EnvironmentConfig,
    EnvironmentConfigurationError,
    FarmConfig,
    FileTerrainConfig,
    GeographicTerrainConfig,
    SyntheticTerrainConfig,
    author_environment_config,
    load_environment_config,
)


def test_terrain_source_discriminator_and_mode_rules() -> None:
    synthetic = EnvironmentConfig.model_validate(
        {
            "case_id": "synthetic",
            "mode": "create",
            "terrain": {"source": "synthetic", "type": "flat"},
            "farm": {"boundary_type": "rectangle", "size_m": 100},
        }
    )
    assert synthetic.mode is CaseMode.CREATE
    assert isinstance(synthetic.terrain, SyntheticTerrainConfig)

    imported = EnvironmentConfig.model_validate(
        {
            "case_id": "imported",
            "mode": "create",
            "terrain": {"source": "file", "path": "/tmp/terrain.tif"},
            "farm": {"boundary_type": "rectangle", "size_m": 100},
        }
    )
    assert isinstance(imported.terrain, FileTerrainConfig)


@pytest.mark.parametrize("source", ["alos", "gsi"])
def test_geographic_sources_require_center(source: str) -> None:
    with pytest.raises(ValueError, match="center_lat and center_lon"):
        GeographicTerrainConfig(source=source)


def test_load_mode_forbids_regeneration_settings() -> None:
    with pytest.raises(ValueError, match="load mode"):
        EnvironmentConfig.model_validate(
            {
                "case_id": "existing",
                "mode": "load",
                "features": {"buildings": {"status": "empty"}},
            }
        )


def test_detection_is_available_only_for_create_or_edit() -> None:
    configured = EnvironmentConfig.model_validate(
        {
            "case_id": "existing",
            "mode": "edit",
            "detection": {
                "imagery": {"source": "gsi_seamlessphoto", "zoom": 17},
                "landcover": {"source": "esa_worldcover", "year": 2021},
                "buildings": {"source": "osm"},
            },
        }
    )
    assert configured.detection.imagery.output_cell_size_m == 1.0
    with pytest.raises(ValueError, match="load mode"):
        EnvironmentConfig.model_validate(
            {"case_id": "existing", "mode": "load", "detection": {}}
        )


def test_invalid_yaml_is_reported_as_configuration_error(tmp_path: Path) -> None:
    config_path = tmp_path / "invalid.yaml"
    config_path.write_text("case_id: broken\nmode: create\n", encoding="utf-8")
    with pytest.raises(EnvironmentConfigurationError):
        load_environment_config(config_path)


def test_scene_crop_configuration_is_loaded(tmp_path: Path) -> None:
    config_path = tmp_path / "scene.yaml"
    config_path.write_text(
        """
case_id: scene-case
mode: create
terrain:
  source: synthetic
  type: flat
  size_m: 1000
  cell_size_m: 10
farm:
  boundary_type: rectangle
  size_m: 400
scene:
  forest_height_m: 10
  forest_boundary_smoothing_m: 5
  crop:
    shape: square
    scale: 1.5
    minimum_margin_m: 100
""",
        encoding="utf-8",
    )

    config, _ = load_environment_config(config_path, start=tmp_path)

    assert config.scene is not None
    assert config.scene.forest_height_m == 10
    assert config.scene.crop.scale == 1.5


def test_python_environment_config_is_saved_as_reproducible_yaml(tmp_path: Path) -> None:
    config = EnvironmentConfig(
        case_id="python-authored-case",
        mode=CaseMode.CREATE,
        terrain=SyntheticTerrainConfig(
            source="synthetic",
            type="hills",
            size_m=100,
            cell_size_m=10,
            relief_m=20,
            seed=5,
        ),
        farm=FarmConfig(boundary_type="rectangle", size_m=80),
    )

    authored = author_environment_config(tmp_path, config, version="v1")

    assert authored.config == config
    assert authored.config_path == (
        tmp_path / "environments/python-authored-case/v1/environment.yaml"
    )
    assert "NotebookのPython設定" in authored.config_path.read_text(encoding="utf-8")
    with pytest.raises(FileExistsError):
        author_environment_config(tmp_path, config, version="v1", overwrite=False)
