from __future__ import annotations

import argparse
import os
from dataclasses import dataclass
from pathlib import Path

import numpy as np
from shapely.geometry import shape

from field_campost import (
    ENVIRONMENT_USD_FILENAME,
    GenesisMeshSource,
    GenesisViewerOptions,
    build_genesis_mesh_scene,
    inspect_genesis,
    read_environment_usd,
    run_genesis_viewer,
    write_genesis_mesh_assets,
)
from field_environment import (
    EnvironmentCase,
    crop_heightmap,
    find_repository_root,
    load_case,
    resolve_case_path,
    scene_crop_geometry,
)


DEFAULT_CASE_ID = "MiyotaMtBase_gsi_3km_v1"


@dataclass(frozen=True)
class ViewBounds:
    min_x_m: float
    min_y_m: float
    max_x_m: float
    max_y_m: float

    @property
    def center(self) -> tuple[float, float]:
        return (
            (self.min_x_m + self.max_x_m) / 2.0,
            (self.min_y_m + self.max_y_m) / 2.0,
        )

    @property
    def span_m(self) -> float:
        return max(self.max_x_m - self.min_x_m, self.max_y_m - self.min_y_m)


def _layer_bounds(layer) -> ViewBounds | None:
    if layer is None or layer.status.value != "available":
        return None
    bounds = [shape(feature["geometry"]).bounds for feature in layer.features]
    return ViewBounds(
        min_x_m=min(item[0] for item in bounds),
        min_y_m=min(item[1] for item in bounds),
        max_x_m=max(item[2] for item in bounds),
        max_y_m=max(item[3] for item in bounds),
    )


def _view_bounds(environment_case: EnvironmentCase, focus: str) -> ViewBounds:
    if environment_case.scene_crop is not None and environment_case.scene_crop.features:
        crop_bounds = _layer_bounds(environment_case.scene_crop)
        if crop_bounds is not None and focus == "terrain":
            return crop_bounds
    if focus == "monitoring":
        monitoring_bounds = _layer_bounds(environment_case.monitoring_area)
        if monitoring_bounds is not None:
            return monitoring_bounds
    if focus in {"monitoring", "farm"}:
        farm_bounds = environment_case.farm_boundary.bounds
        return ViewBounds(
            farm_bounds.min_x_m,
            farm_bounds.min_y_m,
            farm_bounds.max_x_m,
            farm_bounds.max_y_m,
        )
    terrain_bounds = environment_case.heightmap.bounds
    return ViewBounds(
        terrain_bounds.min_x_m,
        terrain_bounds.min_y_m,
        terrain_bounds.max_x_m,
        terrain_bounds.max_y_m,
    )


# Caseの対象範囲からGenesis Viewerの初期視点を決定する．
def create_viewer_options(
    environment_case: EnvironmentCase,
    *,
    focus: str,
    resolution: tuple[int, int],
    camera_fov_deg: float,
) -> GenesisViewerOptions:
    bounds = _view_bounds(environment_case, focus)
    center_x_m, center_y_m = bounds.center
    span_m = max(bounds.span_m, environment_case.heightmap.grid.cell_size_m)
    elevations = environment_case.heightmap.values
    center_z_m = float(np.median(elevations))
    highest_z_m = float(np.max(elevations))
    return GenesisViewerOptions(
        resolution=resolution,
        camera_position=(
            center_x_m - span_m * 0.75,
            center_y_m - span_m * 0.90,
            highest_z_m + max(250.0, span_m * 0.55),
        ),
        camera_look_at=(center_x_m, center_y_m, center_z_m),
        camera_fov_deg=camera_fov_deg,
        refresh_rate_hz=30,
        show_world_frame=True,
        world_frame_size_m=max(20.0, span_m * 0.08),
    )


def _feature_count(layer) -> int:
    if layer is None or layer.status.value != "available":
        return 0
    return len(layer.features)


def _print_case_summary(
    environment_case: EnvironmentCase,
    usd_path: Path,
    viewer_options: GenesisViewerOptions,
) -> None:
    scene_heightmap = crop_heightmap(
        environment_case.heightmap, scene_crop_geometry(environment_case)
    )
    grid = scene_heightmap.grid
    print(f"Case: {environment_case.case_spec.case_id}")
    print(
        "Terrain: "
        f"{grid.width_cells} x {grid.height_cells} cells, "
        f"{grid.cell_size_m:g} m/cell, "
        f"{scene_heightmap.width_m:g} x {scene_heightmap.height_m:g} m"
    )
    print(
        "Elevation: "
        f"{float(np.min(scene_heightmap.values)):.2f} - "
        f"{float(np.max(scene_heightmap.values)):.2f} m"
    )
    print(
        "Scene elements: "
        f"forest={_feature_count(environment_case.forest)}, "
        f"buildings={_feature_count(environment_case.buildings)}, "
        f"facility_buildings={_feature_count(environment_case.facility_buildings)}"
    )
    print(f"USD: {usd_path} ({usd_path.stat().st_size / (1024 * 1024):.1f} MiB)")
    print(f"Viewer camera: {viewer_options.camera_position}")
    print(f"Viewer target: {viewer_options.camera_look_at}")


def _argument_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Open a saved environment Case in the Genesis interactive viewer."
    )
    parser.add_argument("--case-id", default=DEFAULT_CASE_ID)
    parser.add_argument(
        "--cases-root",
        type=Path,
        default=Path("cases"),
        help="Case directory root, relative to the repository root by default.",
    )
    parser.add_argument(
        "--backend",
        choices=("gpu", "cuda", "cpu"),
        default="cpu",
        help="Genesis compute backend. CPU is the JetPack 6.1-compatible viewer default.",
    )
    parser.add_argument("--focus", choices=("monitoring", "farm", "terrain"), default="monitoring")
    parser.add_argument("--width", type=int, default=1280)
    parser.add_argument("--height", type=int, default=720)
    parser.add_argument("--fov", type=float, default=45.0)
    parser.add_argument(
        "--mesh-cache",
        type=Path,
        default=Path("/tmp/shepherd-genesis"),
        help="Directory for OBJ files derived from the Case for Genesis visualization.",
    )
    parser.add_argument(
        "--check-only",
        action="store_true",
        help="Validate the Case, USD, and Genesis dependencies without opening a window.",
    )
    return parser


def main() -> int:
    arguments = _argument_parser().parse_args()
    repository_root = find_repository_root(Path(__file__))
    cases_root = arguments.cases_root
    if not cases_root.is_absolute():
        cases_root = repository_root / cases_root
    case_directory = resolve_case_path(cases_root, arguments.case_id)
    environment_case = load_case(cases_root, arguments.case_id)
    usd_path = case_directory / ENVIRONMENT_USD_FILENAME
    if not usd_path.is_file():
        raise FileNotFoundError(
            f"{usd_path} is missing; generate the Case Mesh/USD in 00_environment.ipynb first"
        )

    usd_summary = read_environment_usd(usd_path)
    if usd_summary.meters_per_unit != 1.0 or usd_summary.up_axis != "Z":
        raise ValueError("environment.usd must use meters and Z-up coordinates")
    viewer_options = create_viewer_options(
        environment_case,
        focus=arguments.focus,
        resolution=(arguments.width, arguments.height),
        camera_fov_deg=arguments.fov,
    )
    _print_case_summary(environment_case, usd_path, viewer_options)

    mesh_directory = arguments.mesh_cache.expanduser().resolve() / arguments.case_id
    mesh_assets = write_genesis_mesh_assets(environment_case, mesh_directory)
    mesh_sources = [
        GenesisMeshSource("terrain", mesh_assets.terrain, (0.42, 0.35, 0.20)),
    ]
    if mesh_assets.forest is not None:
        mesh_sources.append(
            GenesisMeshSource("forest", mesh_assets.forest, (0.04, 0.28, 0.07))
        )
    if mesh_assets.buildings is not None:
        mesh_sources.append(
            GenesisMeshSource("buildings", mesh_assets.buildings, (0.48, 0.48, 0.52))
        )
    if mesh_assets.facility_buildings is not None:
        mesh_sources.append(
            GenesisMeshSource(
                "facility_buildings",
                mesh_assets.facility_buildings,
                (0.85, 0.42, 0.08),
            )
        )
    print("Genesis mesh assets:")
    for source in mesh_sources:
        print(f"  {source.name}: {source.path} ({source.path.stat().st_size / (1024 * 1024):.1f} MiB)")

    genesis_status = inspect_genesis()
    print(f"Genesis: {genesis_status.reason}")
    if arguments.check_only:
        if not genesis_status.mesh_support_available:
            return 2
        print("Check completed; no viewer window was opened.")
        return 0
    if not genesis_status.mesh_support_available:
        raise RuntimeError(genesis_status.reason)
    if not os.environ.get("DISPLAY"):
        raise RuntimeError(
            "DISPLAY is not set; pass the Jetson X11 display and /tmp/.X11-unix into Docker"
        )

    print("Opening Genesis viewer. Close the window or press Ctrl+C in the terminal to finish.")
    genesis_scene = build_genesis_mesh_scene(
        tuple(mesh_sources),
        backend=arguments.backend,
        show_viewer=True,
        viewer_options=viewer_options,
        collision=False,
    )
    print(f"Genesis loaded {len(genesis_scene.entities)} scene entities.")
    run_genesis_viewer(genesis_scene)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
