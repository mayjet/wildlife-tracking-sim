from __future__ import annotations

from pathlib import Path

import pytest

from field_environment import (
    CaseMode,
    EnvironmentConfig,
    EnvironmentConfigurationError,
    FileTerrainConfig,
    GeographicTerrainConfig,
    SyntheticTerrainConfig,
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


def test_invalid_yaml_is_reported_as_configuration_error(tmp_path: Path) -> None:
    config_path = tmp_path / "invalid.yaml"
    config_path.write_text("case_id: broken\nmode: create\n", encoding="utf-8")
    with pytest.raises(EnvironmentConfigurationError):
        load_environment_config(config_path)
