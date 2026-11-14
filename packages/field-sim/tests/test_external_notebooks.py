from __future__ import annotations

import os
from pathlib import Path

import nbformat
import pytest
from nbclient import NotebookClient


def _cell_by_id(notebook, cell_id: str):
    return next(cell for cell in notebook.cells if cell.get("id") == cell_id)


@pytest.mark.integration
@pytest.mark.skipif(
    os.environ.get("RUN_EXTERNAL_TERRAIN_TESTS") != "1",
    reason="set RUN_EXTERNAL_TERRAIN_TESTS=1 for official service integration",
)
def test_alos_environment_and_simulation_notebooks_end_to_end(tmp_path, monkeypatch) -> None:
    repository_root = Path(__file__).resolve().parents[3]
    cases_root = tmp_path / "cases"
    terrain_config = tmp_path / "alos.yaml"
    terrain_config.write_text(
        """
case_id: alos-notebook-integration
mode: create
terrain:
  source: alos
  center_lat: 35.685
  center_lon: 139.77
  size_m: 300
  cell_size_m: 30
farm: {boundary_type: rectangle, size_m: 200}
features:
  buildings: {status: unavailable, source: not acquired}
  forest: {status: unavailable, source: not acquired}
cameras: []
""",
        encoding="utf-8",
    )
    monkeypatch.setenv("WILDLIFE_CASES_ROOT", str(cases_root))
    monkeypatch.setenv("WILDLIFE_EXPERIMENTS_ROOT", str(tmp_path / "experiments"))
    environment_notebook = nbformat.read(
        repository_root / "workspace/00_environment.ipynb", as_version=4
    )
    environment_notebook.cells[1].source = f"CONFIG_FILE = {str(terrain_config)!r}"
    NotebookClient(
        environment_notebook,
        timeout=180,
        kernel_name="python3",
        resources={"metadata": {"path": str(repository_root)}},
    ).execute()

    simulation_notebook = nbformat.read(
        repository_root / "workspace/04_simulation.ipynb", as_version=4
    )
    _cell_by_id(simulation_notebook, "experiment-identification").source = """
experiment_id = "external-notebook-v1"
case_id = "alos-notebook-integration"
configuration_version = "v1"
"""
    _cell_by_id(simulation_notebook, "camera-settings").source = """
camera_placements = [("grid", 40.0)]
camera_counts = [6]
camera_settings = {"pole_height_m": 5.0, "horizontal_fov_deg": 60.0,
                   "vertical_fov_deg": 48.0, "max_observation_distance_m": 42.0}
"""
    _cell_by_id(simulation_notebook, "route-settings").source = """
route_methods = ["direct"]
route_settings = {}
seeds = [5]
"""
    _cell_by_id(simulation_notebook, "visibility-simulation-settings").source = """
visibility_settings = {
    "preview_cell_size_m": 40.0,
    "intermediate_cell_size_m": 10.0,
    "evaluation_cell_size_m": 1.0,
    "deer_height_m": 1.5,
    "sample_heights_m": [0.0, 0.75, 1.5],
}
simulation_settings = {"speed_mps": 1.5, "step_s": 1.0}
"""
    _cell_by_id(simulation_notebook, "waypoint-settings").source = """
waypoint_set_id = "external-corridor-v1"
initial_waypoints = [(-20.0, 0.0), (20.0, 0.0)]
"""
    _cell_by_id(simulation_notebook, "execution-options").source = """
ENABLE_WAYPOINT_EDITOR = False
PREVIEW_LAYOUT_ID = None
VISIBILITY_MAP_CELL_SIZE_M = 40.0
RUN_FORMAL_1M_EVALUATION = False
RUN_BATCH = True
OVERWRITE_GENERATED_YAML = True
OVERWRITE_CASE_RESULTS = False
"""
    NotebookClient(
        simulation_notebook,
        timeout=180,
        kernel_name="python3",
        resources={"metadata": {"path": str(repository_root)}},
    ).execute()
    case_directory = cases_root / "alos-notebook-integration"
    assert (case_directory / "source/jaxa/aw3d30_dsm.tif").is_file()
    assert (case_directory / "environment.usd").is_file()
    dataset = case_directory / "datasets/external-corridor-v1-direct-v1-seed5"
    assert (dataset / "ground_truth.parquet").is_file()
    assert (dataset / "observations/grid-40m-cam6-v1/observations.parquet").is_file()
