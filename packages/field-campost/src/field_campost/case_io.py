from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import yaml
from field_environment import EnvironmentCase, load_case, resolve_case_path
from shepherd_contracts import CameraLayout

from .cameras import load_camera_layout, save_camera_layout
from .mesh import heightmap_to_mesh, validate_mesh_against_heightmap
from .usd import read_environment_usd, write_environment_usd

CAMERA_LAYOUT_FILENAME = "camera_layout.json"
ENVIRONMENT_USD_FILENAME = "environment.usd"


def _update_case_usd_reference(case_directory: Path, environment_case: EnvironmentCase) -> None:
    updated_environment = environment_case.case_spec.environment.model_copy(
        update={"environment_usd": ENVIRONMENT_USD_FILENAME}
    )
    updated_spec = environment_case.case_spec.model_copy(
        update={"environment": updated_environment}
    )
    updated_case = replace(environment_case, case_spec=updated_spec)
    destination = case_directory / "case.yaml"
    temporary = destination.with_name(".case.yaml.tmp")
    temporary.write_text(
        yaml.safe_dump(
            updated_case.document.model_dump(mode="json"),
            sort_keys=False,
            allow_unicode=True,
        ),
        encoding="utf-8",
    )
    temporary.replace(destination)


def save_case_scene(
    cases_root: str | Path,
    case_id: str,
    layout: CameraLayout,
    *,
    overwrite: bool = False,
) -> tuple[Path, Path]:
    environment_case = load_case(cases_root, case_id)
    case_directory = resolve_case_path(cases_root, case_id)
    layout_path = case_directory / CAMERA_LAYOUT_FILENAME
    usd_path = case_directory / ENVIRONMENT_USD_FILENAME
    existing = [path for path in (layout_path, usd_path) if path.exists()]
    if existing and not overwrite:
        raise FileExistsError(
            "Phase 3 Case artifacts already exist: " + ", ".join(str(path) for path in existing)
        )
    for camera in layout.cameras:
        ground_z_m = environment_case.heightmap.elevation_at(
            camera.position.x_m, camera.position.y_m
        )
        if camera.position.z_m <= ground_z_m:
            raise ValueError(f"camera {camera.camera_id!r} must be above the terrain surface")
    mesh = heightmap_to_mesh(environment_case.heightmap)
    validate_mesh_against_heightmap(mesh, environment_case.heightmap)
    save_camera_layout(layout, layout_path, overwrite=overwrite)
    try:
        write_environment_usd(
            mesh,
            layout,
            usd_path,
            heightmap=environment_case.heightmap,
            buildings=environment_case.buildings,
            forest=environment_case.forest,
            overwrite=overwrite,
        )
        summary = read_environment_usd(usd_path)
        if summary.layout != layout:
            raise ValueError("CameraLayout changed during USD round trip")
        if summary.meters_per_unit != 1.0 or summary.up_axis != "Z":
            raise ValueError("USD coordinate metadata is invalid")
        _update_case_usd_reference(case_directory, environment_case)
    except Exception:
        if not existing:
            layout_path.unlink(missing_ok=True)
            usd_path.unlink(missing_ok=True)
        raise
    return layout_path, usd_path


def load_case_camera_layout(cases_root: str | Path, case_id: str) -> CameraLayout:
    case_directory = resolve_case_path(cases_root, case_id)
    return load_camera_layout(case_directory / CAMERA_LAYOUT_FILENAME)
