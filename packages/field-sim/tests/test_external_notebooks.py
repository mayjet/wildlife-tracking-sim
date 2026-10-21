from __future__ import annotations

import os
from pathlib import Path

import nbformat
import pytest
from nbclient import NotebookClient


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

    simulation_config = tmp_path / "simulation.yaml"
    simulation_config.write_text(
        """
case_id: alos-notebook-integration
dataset_id: external-stationary
seed: 5
duration_s: 2
step_s: 1
motion:
  kind: stationary
  position: {x_m: 0, y_m: 0}
""",
        encoding="utf-8",
    )
    simulation_notebook = nbformat.read(
        repository_root / "workspace/04_simulation.ipynb", as_version=4
    )
    simulation_notebook.cells[1].source = f"CONFIG_FILE = {str(simulation_config)!r}"
    NotebookClient(
        simulation_notebook,
        timeout=180,
        kernel_name="python3",
        resources={"metadata": {"path": str(repository_root)}},
    ).execute()
    case_directory = cases_root / "alos-notebook-integration"
    assert (case_directory / "source/jaxa/aw3d30_dsm.tif").is_file()
    assert (case_directory / "environment.usd").is_file()
    assert (case_directory / "datasets/external-stationary/ground_truth.parquet").is_file()
