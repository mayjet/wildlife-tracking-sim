from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pytest
import rasterio
from pyproj import CRS
from rasterio.transform import from_origin

from field_environment import (
    FeatureLayerStatus,
    TraversabilityValue,
    load_case,
    run_environment_workflow,
)


def _write_yaml(path: Path, content: str) -> Path:
    path.write_text(content, encoding="utf-8")
    return path


def test_create_load_edit_preserves_unmodified_case_assets(tmp_path: Path) -> None:
    root = Path(__file__).resolve().parents[3]
    cases_root = tmp_path / "cases"
    create_config = _write_yaml(
        tmp_path / "create.yaml",
        """
case_id: workflow-case
mode: create
terrain: {source: synthetic, type: flat, size_m: 100, cell_size_m: 10, seed: 7}
farm: {boundary_type: rectangle, size_m: 80}
features:
  buildings: {status: unavailable, source: not acquired}
  forest: {status: empty, source: user-confirmed empty}
  difficult_slope_deg: 30
""",
    )
    created = run_environment_workflow(
        create_config, repository_start=root, cases_root=cases_root
    )
    case_directory = created.case_directory
    assert (case_directory / "terrain.tif").is_file()
    assert (case_directory / "forest.geojson").is_file()
    assert created.environment_case.buildings.status is FeatureLayerStatus.UNAVAILABLE
    assert created.environment_case.forest.status is FeatureLayerStatus.EMPTY
    assert np.all(
        created.environment_case.traversability.values == TraversabilityValue.UNKNOWN
    )
    sentinel = case_directory / "camera_layout.json"
    sentinel.write_text('{"preserve": true}', encoding="utf-8")

    load_config = _write_yaml(
        tmp_path / "load.yaml", "case_id: workflow-case\nmode: load\n"
    )
    loaded = run_environment_workflow(load_config, repository_start=root, cases_root=cases_root)
    assert loaded.environment_case.heightmap.grid == created.environment_case.heightmap.grid

    edit_config = _write_yaml(
        tmp_path / "edit.yaml",
        """
case_id: workflow-case
mode: edit
farm: {boundary_type: rectangle, size_m: 60}
""",
    )
    edited = run_environment_workflow(edit_config, repository_start=root, cases_root=cases_root)
    assert edited.environment_case.farm_boundary.bounds.max_x_m == 30.0
    assert json.loads(sentinel.read_text(encoding="utf-8")) == {"preserve": True}


def test_create_refuses_existing_case(tmp_path: Path) -> None:
    root = Path(__file__).resolve().parents[3]
    config = _write_yaml(
        tmp_path / "create.yaml",
        """
case_id: duplicate
mode: create
terrain: {source: synthetic, type: ridge, size_m: 40, cell_size_m: 10}
farm: {boundary_type: rectangle, size_m: 20}
""",
    )
    cases_root = tmp_path / "cases"
    run_environment_workflow(config, repository_start=root, cases_root=cases_root)
    with pytest.raises(FileExistsError):
        run_environment_workflow(config, repository_start=root, cases_root=cases_root)


def test_file_source_uses_same_environment_case_workflow(tmp_path: Path) -> None:
    root = Path(__file__).resolve().parents[3]
    source_path = tmp_path / "terrain.tif"
    crs = CRS.from_proj4(
        "+proj=aeqd +lat_0=35 +lon_0=139 +datum=WGS84 +units=m +no_defs"
    )
    with rasterio.open(
        source_path,
        "w",
        driver="GTiff",
        width=10,
        height=10,
        count=1,
        dtype="float32",
        crs=crs,
        transform=from_origin(-50, 50, 10, 10),
    ) as dataset:
        dataset.write(np.arange(100, dtype=np.float32).reshape(10, 10), 1)
    config = _write_yaml(
        tmp_path / "file.yaml",
        f"""
case_id: imported-workflow
mode: create
terrain: {{source: file, path: {source_path}, size_m: 80, cell_size_m: 10}}
farm: {{boundary_type: rectangle, size_m: 60}}
""",
    )
    result = run_environment_workflow(
        config, repository_start=root, cases_root=tmp_path / "cases"
    )
    assert result.environment_case.provenance.source == "file"
    assert result.environment_case.case_spec.environment.terrain == "terrain.tif"
    assert (result.case_directory / "source/import/terrain.tif").is_file()
