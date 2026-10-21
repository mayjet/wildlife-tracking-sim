from __future__ import annotations

import numpy as np
import pytest

from field_environment import load_case, save_case


def test_case_save_and_load_round_trip(tmp_path, environment_case) -> None:
    case_directory = save_case(environment_case, tmp_path)
    assert case_directory == tmp_path / environment_case.case_spec.case_id
    assert {path.name for path in case_directory.iterdir()} == {
        "case.yaml",
        "terrain.tif",
        "farm_boundary.geojson",
        "datasets",
        "runs",
    }
    restored = load_case(tmp_path, environment_case.case_spec.case_id)
    assert restored.case_spec == environment_case.case_spec
    assert restored.generation == environment_case.generation
    assert restored.heightmap.grid == environment_case.heightmap.grid
    np.testing.assert_array_equal(restored.heightmap.values, environment_case.heightmap.values)
    assert restored.farm_boundary.polygon.equals_exact(
        environment_case.farm_boundary.polygon, tolerance=0.0
    )


def test_existing_case_is_not_overwritten_by_default(tmp_path, environment_case) -> None:
    save_case(environment_case, tmp_path)
    with pytest.raises(FileExistsError):
        save_case(environment_case, tmp_path)


def test_explicit_overwrite_replaces_case(tmp_path, environment_case) -> None:
    save_case(environment_case, tmp_path)
    destination = save_case(environment_case, tmp_path, overwrite=True)
    assert (destination / "case.yaml").is_file()

