from __future__ import annotations

from pathlib import Path

import nbformat
from nbclient import NotebookClient


def _cell_by_id(notebook, cell_id: str):
    return next(cell for cell in notebook.cells if cell.get("id") == cell_id)


def test_environment_notebook_executes_end_to_end(tmp_path, monkeypatch) -> None:
    repository_root = Path(__file__).resolve().parents[3]
    notebook_path = repository_root / "workspace" / "00_environment.ipynb"
    cases_root = tmp_path / "cases"
    config_path = tmp_path / "terrain.yaml"
    config_path.write_text(
        """
case_id: notebook-environment-case
mode: create
terrain: {source: synthetic, type: hills, size_m: 100, cell_size_m: 10, relief_m: 20, seed: 5}
farm: {boundary_type: rectangle, size_m: 80}
features:
  buildings: {status: unavailable, source: not acquired}
  forest: {status: unavailable, source: not acquired}
cameras:
  - camera_id: test-camera
    x_m: -30
    y_m: 0
    height_above_ground_m: 3
    yaw_deg: 0
""",
        encoding="utf-8",
    )
    monkeypatch.setenv("WILDLIFE_CASES_ROOT", str(cases_root))
    notebook = nbformat.read(notebook_path, as_version=4)
    notebook.cells[1].source = f"CONFIG_FILE = {str(config_path)!r}"
    client = NotebookClient(
        notebook,
        timeout=120,
        kernel_name="python3",
        resources={"metadata": {"path": str(repository_root)}},
    )
    client.execute()
    case_directory = cases_root / "notebook-environment-case"
    assert (case_directory / "case.yaml").is_file()
    assert (case_directory / "terrain.tif").is_file()
    assert (case_directory / "farm_boundary.geojson").is_file()
    assert (case_directory / "camera_layout.json").is_file()
    assert (case_directory / "environment.usd").is_file()
    assert (case_directory / "previews/elevation.png").is_file()


def test_python_environment_notebook_executes_end_to_end(tmp_path, monkeypatch) -> None:
    repository_root = Path(__file__).resolve().parents[3]
    notebook_path = repository_root / "workspace" / "00_environment_python.ipynb"
    cases_root = tmp_path / "cases"
    generated_root = tmp_path / "generated"
    monkeypatch.setenv("WILDLIFE_CASES_ROOT", str(cases_root))
    monkeypatch.setenv("WILDLIFE_ENV_CONFIG_ROOT", str(generated_root))
    notebook = nbformat.read(notebook_path, as_version=4)
    _cell_by_id(notebook, "case-settings").source = """
case_id = "python-notebook-environment-case"
mode = CaseMode.CREATE
configuration_version = "v1"
source_case_id = None
overwrite_generated_yaml = True
"""
    _cell_by_id(notebook, "terrain-settings").source = """
from field_environment import SyntheticTerrainConfig
terrain_settings = SyntheticTerrainConfig(
    source="synthetic", type="hills", size_m=100, cell_size_m=10,
    relief_m=20, seed=5,
)
farm_settings = FarmConfig(boundary_type="rectangle", size_m=80)
"""
    _cell_by_id(notebook, "detection-settings").source = """
detection_settings = None
features_settings = EnvironmentFeaturesConfig.model_validate({
    "buildings": {"status": "unavailable", "source": "not acquired"},
    "forest": {"status": "unavailable", "source": "not acquired"},
})
"""
    _cell_by_id(notebook, "scene-settings").source = """
scene_settings = SceneConfig(
    forest_height_m=10,
    crop=SceneCropConfig(enabled=False),
)
camera_settings = (
    FixedCameraConfig(
        camera_id="test-camera", x_m=-30, y_m=0,
        height_above_ground_m=3, yaw_deg=0,
    ),
)
"""
    NotebookClient(
        notebook,
        timeout=120,
        kernel_name="python3",
        resources={"metadata": {"path": str(repository_root)}},
    ).execute()
    case_directory = cases_root / "python-notebook-environment-case"
    generated_config = (
        generated_root
        / "environments/python-notebook-environment-case/v1/environment.yaml"
    )
    assert generated_config.is_file()
    assert (case_directory / "case.yaml").is_file()
    assert (case_directory / "terrain.tif").is_file()
    assert (case_directory / "farm_boundary.geojson").is_file()
    assert (case_directory / "camera_layout.json").is_file()
    assert (case_directory / "environment.usd").is_file()
    assert (case_directory / "previews/elevation.png").is_file()
