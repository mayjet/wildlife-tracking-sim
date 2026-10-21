from __future__ import annotations

from pathlib import Path

import nbformat
from nbclient import NotebookClient

from field_environment import FarmBoundary, TerrainGridSpec, create_synthetic_case, save_case


def test_simulation_notebook_executes(tmp_path, monkeypatch) -> None:
    repository_root = Path(__file__).resolve().parents[3]
    cases_root = tmp_path / "cases"
    case_id = "notebook-simulation-case"
    environment_case = create_synthetic_case(
        case_id=case_id,
        terrain_kind="flat",
        grid=TerrainGridSpec.from_extent(100.0, 100.0, 10.0, min_x_m=-50, min_y_m=-50),
        farm_boundary=FarmBoundary.rectangle(
            min_x_m=-40,
            min_y_m=-40,
            max_x_m=40,
            max_y_m=40,
            coordinate_system_name=f"{case_id}-local-enu",
        ),
        generation_parameters={"elevation_m": 5.0},
        seed=1,
    )
    save_case(environment_case, cases_root)
    config_path = tmp_path / "simulation.yaml"
    config_path.write_text(
        f"""
case_id: {case_id}
dataset_id: notebook-dataset
seed: 4
duration_s: 2
step_s: 1
motion:
  kind: stationary
  position: {{x_m: 0, y_m: 0}}
""",
        encoding="utf-8",
    )
    monkeypatch.setenv("WILDLIFE_CASES_ROOT", str(cases_root))
    notebook = nbformat.read(repository_root / "workspace/04_simulation.ipynb", as_version=4)
    notebook.cells[1].source = f"CONFIG_FILE = {str(config_path)!r}"
    NotebookClient(
        notebook,
        timeout=120,
        kernel_name="python3",
        resources={"metadata": {"path": str(repository_root)}},
    ).execute()
    assert (cases_root / case_id / "datasets/notebook-dataset/ground_truth.parquet").is_file()
