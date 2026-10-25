from pathlib import Path

import pytest

from field_campost import (
    load_case_camera_layout,
    read_environment_usd,
    save_case_scene,
)
from field_environment import load_case, save_case


def test_case_scene_round_trip(tmp_path, environment_case, camera_layout):
    save_case(environment_case, tmp_path)

    layout_path, usd_path = save_case_scene(tmp_path, environment_case.case_spec.case_id, camera_layout)

    assert layout_path == tmp_path / environment_case.case_spec.case_id / "camera_layout.json"
    assert usd_path == tmp_path / environment_case.case_spec.case_id / "environment.usd"
    assert load_case_camera_layout(tmp_path, environment_case.case_spec.case_id) == camera_layout
    assert read_environment_usd(usd_path).layout == camera_layout
    loaded_case = load_case(tmp_path, environment_case.case_spec.case_id)
    assert loaded_case.case_spec.environment.environment_usd == "environment.usd"
    assert (tmp_path / environment_case.case_spec.case_id / "field_summary.json").is_file()


def test_case_scene_does_not_overwrite_implicitly(tmp_path, environment_case, camera_layout):
    save_case(environment_case, tmp_path)
    save_case_scene(tmp_path, environment_case.case_spec.case_id, camera_layout)

    with pytest.raises(FileExistsError):
        save_case_scene(tmp_path, environment_case.case_spec.case_id, camera_layout)


def test_case_scene_rejects_camera_below_ground(tmp_path, environment_case, camera_layout):
    save_case(environment_case, tmp_path)
    camera = camera_layout.cameras[0]
    invalid_camera = camera.model_copy(
        update={
            "position": camera.position.model_copy(update={"z_m": -100.0})
        }
    )
    invalid_layout = camera_layout.model_copy(
        update={"cameras": (invalid_camera,) + camera_layout.cameras[1:]}
    )

    with pytest.raises(ValueError, match="above the terrain"):
        save_case_scene(tmp_path, environment_case.case_spec.case_id, invalid_layout)

    assert not (tmp_path / environment_case.case_spec.case_id / "environment.usd").exists()


def test_case_artifact_names_stay_within_case(tmp_path, environment_case, camera_layout):
    save_case(environment_case, tmp_path)
    layout_path, usd_path = save_case_scene(tmp_path, environment_case.case_spec.case_id, camera_layout)
    case_path = (tmp_path / environment_case.case_spec.case_id).resolve()

    assert Path(layout_path).resolve().parent == case_path
    assert Path(usd_path).resolve().parent == case_path
