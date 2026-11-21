from __future__ import annotations

from pathlib import Path

import nbformat
import pandas as pd
from nbclient import NotebookClient

from field_environment import FarmBoundary, TerrainGridSpec, create_synthetic_case, save_case


def test_benchmark_notebook_executes_with_observation_only_input(tmp_path, monkeypatch) -> None:
    repository_root = Path(__file__).resolve().parents[3]
    cases_root = tmp_path / "cases"
    case_id = "benchmark-notebook-case"
    dataset_id = "benchmark-notebook-dataset"
    layout_id = "benchmark-layout"
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
    dataset_directory = cases_root / case_id / "datasets" / dataset_id
    observation_directory = dataset_directory / "observations" / layout_id
    observation_directory.mkdir(parents=True)
    pd.DataFrame(
        {
            "timestamp_s": [0.0, 1.0, 2.0],
            "truth_id": ["deer-a"] * 3,
            "group_truth_id": ["herd-a"] * 3,
            "is_group_leader": [True] * 3,
            "x_m": [0.0, 1.0, 2.0],
            "y_m": [0.0, 0.0, 0.0],
        }
    ).to_parquet(dataset_directory / "ground_truth.parquet", index=False)
    pd.DataFrame(
        {
            "timestamp_s": [0.0, 1.0, 2.0],
            "camera_id": ["camera-a"] * 3,
            "observation_id": ["obs-0", "obs-1", "obs-2"],
            "x_m": [0.0, 1.0, 2.0],
            "y_m": [0.0, 0.0, 0.0],
            "age_class": ["UNKNOWN"] * 3,
        }
    ).to_parquet(observation_directory / "observations.parquet", index=False)
    monkeypatch.setenv("WILDLIFE_CASES_ROOT", str(cases_root))

    notebook = nbformat.read(repository_root / "workspace/05_benchmark.ipynb", as_version=4)
    for cell in notebook.cells:
        if cell.cell_type != "code":
            continue
        if "CASE_ID =" in cell.source:
            cell.source = f'''
CASE_ID = {case_id!r}
BENCHMARK_ID = "benchmark-notebook-v1"
DATASET_IDS = [{dataset_id!r}]
LAYOUT_IDS = [{layout_id!r}]
tracker_methods = ["last_observation", "constant_velocity"]
TRACKER_SEED = 42
OVERWRITE = False
ENABLE_RERUN = False
'''
        if "REPOSITORY_ROOT = find_repository_root()" in cell.source:
            cell.source = cell.source.replace(
                'CASES_ROOT = REPOSITORY_ROOT / "cases"',
                'CASES_ROOT = Path(__import__("os").environ["WILDLIFE_CASES_ROOT"])',
            )
    NotebookClient(
        notebook,
        timeout=120,
        kernel_name="python3",
        resources={"metadata": {"path": str(repository_root)}},
    ).execute()

    runs = cases_root / case_id / "runs"
    assert len(list(runs.glob("*/tracking.parquet"))) == 2
    assert len(list(runs.glob("*/benchmark_metrics.json"))) == 2
    assert len(list(runs.glob("*/group_benchmark_metrics.json"))) == 2
    assert (
        cases_root
        / case_id
        / "benchmarks"
        / "benchmark-notebook-v1"
        / "condition_results.parquet"
    ).is_file()
