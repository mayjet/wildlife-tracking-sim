from __future__ import annotations

from pathlib import Path

import nbformat
from nbclient import NotebookClient

from field_environment import FarmBoundary, TerrainGridSpec, create_synthetic_case, save_case


def _cell_by_id(notebook, cell_id: str):
    return next(cell for cell in notebook.cells if cell.get("id") == cell_id)


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
    monkeypatch.setenv("WILDLIFE_CASES_ROOT", str(cases_root))
    monkeypatch.setenv("WILDLIFE_EXPERIMENTS_ROOT", str(tmp_path / "experiments"))
    notebook = nbformat.read(repository_root / "workspace/04_simulation.ipynb", as_version=4)
    _cell_by_id(notebook, "experiment-identification").source = f"""
experiment_id = "notebook-experiment-v1"
case_id = {case_id!r}
configuration_version = "v1"
"""
    _cell_by_id(notebook, "camera-settings").source = """
camera_placements = [("grid", 40.0), ("uniform", 4)]
camera_counts = [6]
camera_settings = {
    "pole_height_m": 5.0,
    "horizontal_fov_deg": 60.0,
    "vertical_fov_deg": 48.0,
    "max_observation_distance_m": 42.0,
}
"""
    _cell_by_id(notebook, "route-settings").source = """
route_methods = ["direct"]
route_settings = {}
seeds = [4]
"""
    _cell_by_id(notebook, "visibility-simulation-settings").source = """
visibility_settings = {
    "preview_cell_size_m": 40.0,
    "intermediate_cell_size_m": 10.0,
    "evaluation_cell_size_m": 1.0,
    "deer_height_m": 1.5,
    "sample_heights_m": [0.0, 0.75, 1.5],
}
simulation_settings = {"speed_mps": 1.5, "step_s": 1.0}
"""
    _cell_by_id(notebook, "waypoint-settings").source = """
waypoint_set_id = "notebook-corridor-v1"
initial_waypoints = [(-20.0, 0.0), (20.0, 0.0)]
"""
    _cell_by_id(notebook, "execution-options").source = """
ENABLE_WAYPOINT_EDITOR = False
PREVIEW_LAYOUT_ID = None
VISIBILITY_MAP_CELL_SIZE_M = 40.0
RUN_FORMAL_1M_EVALUATION = False
RUN_BATCH = True
OVERWRITE_GENERATED_YAML = True
OVERWRITE_CASE_RESULTS = False
"""
    NotebookClient(
        notebook,
        timeout=120,
        kernel_name="python3",
        resources={"metadata": {"path": str(repository_root)}},
    ).execute()
    dataset = cases_root / case_id / "datasets/notebook-corridor-v1-direct-v1-seed4"
    assert (dataset / "ground_truth.parquet").is_file()
    assert (dataset / "observations/grid-40m-cam6-v1/observations.parquet").is_file()
    assert (
        cases_root
        / case_id
        / "observation_point_layouts/uniform-4points-cam6-v1/layout.json"
    ).is_file()
