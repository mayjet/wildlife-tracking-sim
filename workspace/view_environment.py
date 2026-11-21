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
    GenesisValidationRay,
    GenesisVisibilityOverlay,
    GenesisViewerOptions,
    build_genesis_mesh_scene,
    create_genesis_deer_proxy,
    drape_genesis_route_overlay,
    draw_genesis_experiment_overlays,
    inspect_genesis,
    load_observation_point_layout,
    read_environment_usd,
    run_genesis_viewer,
    write_experiment_scene_layers,
    write_genesis_mesh_assets,
    write_observation_infrastructure_assets,
)
from field_environment import (
    EnvironmentCase,
    crop_heightmap,
    find_repository_root,
    load_case,
    resolve_case_path,
    scene_crop_geometry,
)
from field_sim import (
    build_phase7_validation_report,
    load_resolved_route,
    load_visibility_map,
    save_phase7_validation_report,
    visibility_overlay_positions,
)


DEFAULT_CASE_ID = "MiyotaMtBase_gsi_3km_v3"
DEFAULT_LAYOUT_ID = "grid-40m-cam6-v1"


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


def _selected_point(layout, point_id: str | None, environment_case: EnvironmentCase):
    if point_id is not None:
        try:
            return next(point for point in layout.points if point.point_id == point_id)
        except StopIteration as error:
            raise ValueError(f"Observation point not found: {point_id}") from error
    centroid = environment_case.farm_boundary.polygon.centroid
    return min(
        layout.points,
        key=lambda point: (point.position.x_m - centroid.x) ** 2
        + (point.position.y_m - centroid.y) ** 2,
    )


def _camera_viewer_options(point, resolution: tuple[int, int]) -> GenesisViewerOptions:
    return GenesisViewerOptions(
        resolution=resolution,
        camera_position=(
            point.position.x_m - 32.0,
            point.position.y_m - 32.0,
            point.position.z_m + 22.0,
        ),
        camera_look_at=(point.position.x_m, point.position.y_m, point.position.z_m),
        camera_fov_deg=55.0,
        refresh_rate_hz=30,
        show_world_frame=True,
        world_frame_size_m=5.0,
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
    parser.add_argument("--layout-id", default=DEFAULT_LAYOUT_ID)
    parser.add_argument(
        "--mode",
        choices=(
            "environment",
            "observation-points",
            "camera",
            "visibility",
            "route",
            "validation",
            "all",
        ),
        default="all",
        help="Select physical objects and viewer-only validation overlays.",
    )
    parser.add_argument(
        "--point-id",
        help="Observation point used for the detailed camera/FOV view.",
    )
    parser.add_argument(
        "--route-id",
        action="append",
        default=[],
        help="Resolved route to draw. Repeat for multiple routes.",
    )
    parser.add_argument(
        "--all-routes",
        action="store_true",
        help="Draw every saved route variant. This can make the viewer crowded.",
    )
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
    parser.add_argument(
        "--visibility-max-points",
        type=int,
        default=8000,
        help="Maximum visible and hidden 1 m samples drawn as a sparse UI overlay.",
    )
    parser.add_argument(
        "--no-report",
        action="store_true",
        help="Do not update previews/genesis_validation_report.json.",
    )
    return parser


def _visibility_path(case_directory: Path, layout_id: str) -> Path:
    directory = case_directory / "visibility_maps" / layout_id
    candidates = (
        directory / "visibility-1m-binary.npz",
        directory / "visibility-1m.npz",
        directory / "visibility-10m.npz",
    )
    for candidate in candidates:
        if candidate.is_file():
            return candidate
    raise FileNotFoundError(f"No visibility map found for layout: {layout_id}")


def _saved_route_ids(case_directory: Path) -> list[str]:
    return sorted(path.parent.name for path in (case_directory / "routes").glob("*/variants/*/route.json"))


def _load_routes(cases_root: Path, case_id: str, case_directory: Path, arguments):
    available = _saved_route_ids(case_directory)
    requested = available if arguments.all_routes else list(arguments.route_id)
    if not requested and available:
        requested = [available[0]]
    return tuple(load_resolved_route(cases_root, case_id, route_id) for route_id in requested)


def _route_overlay(environment_case: EnvironmentCase, route, color):
    return drape_genesis_route_overlay(
        environment_case,
        route_id=route.definition.route_id,
        coordinates=route.points[["x_m", "y_m"]].to_numpy(dtype=np.float64),
        waypoints=np.asarray(
            [(point.x_m, point.y_m) for point in route.waypoint_set.waypoints],
            dtype=np.float64,
        ),
        color=color,
    )


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
    layout = (
        None
        if arguments.mode == "environment"
        else load_observation_point_layout(cases_root, arguments.case_id, arguments.layout_id)
    )
    selected_point = (
        None
        if layout is None
        else _selected_point(layout, arguments.point_id, environment_case)
    )
    viewer_options = create_viewer_options(
        environment_case,
        focus=arguments.focus,
        resolution=(arguments.width, arguments.height),
        camera_fov_deg=arguments.fov,
    )
    if (
        arguments.mode == "camera"
        and selected_point is not None
        and arguments.point_id is not None
    ):
        viewer_options = _camera_viewer_options(
            selected_point, (arguments.width, arguments.height)
        )
    _print_case_summary(environment_case, usd_path, viewer_options)
    if layout is not None and selected_point is not None:
        print(
            f"Observation layout: {layout.layout_id}, "
            f"points={len(layout.points)}, cameras={len(layout.camera_layout.cameras)}"
        )
        print(f"Selected observation point: {selected_point.point_id}")

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
    if layout is not None:
        infrastructure = write_observation_infrastructure_assets(
            layout,
            case_directory / "observation_point_layouts" / layout.layout_id,
        )
        scene_layers = write_experiment_scene_layers(case_directory, layout.layout_id)
        mesh_sources.extend(
            (
                GenesisMeshSource(
                    "observation_poles", infrastructure.poles, (0.18, 0.18, 0.20)
                ),
                GenesisMeshSource(
                    "camera_housings",
                    infrastructure.camera_housings,
                    (0.05, 0.18, 0.30),
                ),
            )
        )
        print(f"Infrastructure USD: {infrastructure.infrastructure_usda}")
        print(f"Composed USD scene: {scene_layers.scene_usda}")

    needs_visibility = arguments.mode in {"visibility", "validation", "all"} or arguments.check_only
    needs_routes = arguments.mode in {"route", "validation", "all"} or arguments.check_only
    visibility_map = None
    visibility_overlay = None
    if needs_visibility:
        visibility_file = _visibility_path(case_directory, layout.layout_id)
        visibility_map = load_visibility_map(visibility_file)
        visible, hidden = visibility_overlay_positions(
            environment_case,
            visibility_map,
            max_points_per_class=arguments.visibility_max_points,
        )
        visibility_overlay = GenesisVisibilityOverlay(visible, hidden)
        print(
            f"Visibility map: {visibility_file.name}, "
            f"visible UI points={len(visible):,}, hidden UI points={len(hidden):,}"
        )
    routes = _load_routes(
        cases_root, arguments.case_id, case_directory, arguments
    ) if needs_routes else ()
    colors = (
        (1.0, 0.10, 0.75, 0.98),
        (0.05, 0.90, 1.0, 0.98),
        (0.75, 0.20, 1.0, 0.98),
        (0.65, 1.0, 0.05, 0.98),
    )
    route_overlays = tuple(
        _route_overlay(environment_case, route, colors[index % len(colors)])
        for index, route in enumerate(routes)
    )
    for route in routes:
        print(f"Route: {route.definition.route_id}, {route.length_m:.1f} m")
    deer_proxies = tuple(
        create_genesis_deer_proxy(
            environment_case,
            truth_id=f"route-preview-{route.definition.route_id}",
            x_m=float(route.points.iloc[0].x_m),
            y_m=float(route.points.iloc[0].y_m),
            heading_rad=float(route.points.iloc[0].heading_rad),
        )
        for route in routes
        if len(route.points)
    )

    report = None
    validation_rays = ()
    if visibility_map is not None and not arguments.no_report:
        if layout is None:
            raise RuntimeError("visibility validation requires an observation layout")
        report = build_phase7_validation_report(
            environment_case, layout, visibility_map, routes
        )
        report_path = save_phase7_validation_report(cases_root, report)
        validation_rays = tuple(
            GenesisValidationRay(
                start=tuple(sample["ray_start"]),
                end=tuple(sample["ray_end"]),
                visible=sample["recomputed_class"] == "FULLY_VISIBLE",
                reason=sample["recomputed_failure"],
            )
            for sample in report["representative_visibility_samples"]
            if sample["ray_start"] is not None and sample["ray_end"] is not None
        )
        print(f"Validation report: {report_path} ({report['status']})")
    print("Genesis mesh assets:")
    for source in mesh_sources:
        print(f"  {source.name}: {source.path} ({source.path.stat().st_size / (1024 * 1024):.1f} MiB)")

    genesis_status = inspect_genesis()
    print(f"Genesis: {genesis_status.reason}")
    if arguments.check_only:
        if not genesis_status.mesh_support_available:
            return 2
        print("Check completed; no viewer window was opened.")
        return 0 if report is None or report["status"] == "passed" else 3
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
    if layout is not None and selected_point is not None:
        draw_genesis_experiment_overlays(
            genesis_scene,
            layout,
            selected_point_id=selected_point.point_id,
            show_fov=arguments.mode in {"camera", "validation", "all"},
            visibility=(
                visibility_overlay
                if arguments.mode in {"visibility", "validation", "all"}
                else None
            ),
            routes=route_overlays,
            rays=validation_rays if arguments.mode in {"validation", "all"} else (),
            deer_proxies=deer_proxies,
        )
    print(f"Genesis loaded {len(genesis_scene.entities)} scene entities.")
    run_genesis_viewer(genesis_scene)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
