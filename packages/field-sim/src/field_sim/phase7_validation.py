from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from pathlib import Path

import numpy as np
from shepherd_contracts import GroundTruthFrame, GroundTruthState, ObservationPointLayout, Position3D

from field_environment import EnvironmentCase, TraversabilityValue, resolve_case_path

from .observations import (
    VisibilityClass,
    VisibilityConfig,
    VisibilityFailure,
    VisibilityMap,
    _build_layout_index,
    _evaluate_target,
    generate_observations,
    visibility_map_metrics,
)
from .occlusion import AnalyticRaycastBackend
from .routes import ResolvedRoute


@dataclass(frozen=True)
class Phase7VisibilitySample:
    x_m: float
    y_m: float
    ground_z_m: float
    expected_class: str
    expected_failure: str
    recomputed_class: str
    recomputed_failure: str
    camera_id: str | None
    ray_start: tuple[float, float, float] | None
    ray_end: tuple[float, float, float] | None
    matches_saved_map: bool


def _sample_indices(mask: np.ndarray, count: int) -> np.ndarray:
    candidates = np.argwhere(mask)
    if len(candidates) <= count:
        return candidates
    selection = np.linspace(0, len(candidates) - 1, count, dtype=int)
    return candidates[selection]


def visibility_overlay_positions(
    environment_case: EnvironmentCase,
    visibility_map: VisibilityMap,
    *,
    max_points_per_class: int = 8000,
    z_offset_m: float = 0.15,
) -> tuple[np.ndarray, np.ndarray]:
    if max_points_per_class <= 0:
        raise ValueError("max_points_per_class must be positive")

    def positions(mask: np.ndarray) -> np.ndarray:
        output = []
        for y_index, x_index in _sample_indices(mask, max_points_per_class):
            x_m = float(visibility_map.x_centers_m[x_index])
            y_m = float(visibility_map.y_centers_m[y_index])
            z_m = environment_case.heightmap.surface_elevation_at(x_m, y_m)
            output.append((x_m, y_m, z_m + z_offset_m))
        return np.asarray(output, dtype=np.float64).reshape((-1, 3))

    visible = positions(visibility_map.classes == VisibilityClass.FULLY_VISIBLE)
    hidden = positions(visibility_map.classes == VisibilityClass.NOT_VISIBLE)
    return visible, hidden


def _representative_cells(visibility_map: VisibilityMap) -> list[tuple[int, int]]:
    selected = []
    full = np.argwhere(visibility_map.classes == VisibilityClass.FULLY_VISIBLE)
    if len(full):
        selected.append(tuple(map(int, full[len(full) // 2])))
    hidden = visibility_map.classes == VisibilityClass.NOT_VISIBLE
    for failure_code, _failure in enumerate(VisibilityFailure):
        candidates = np.argwhere(
            np.logical_and(hidden, visibility_map.failure_codes == failure_code)
        )
        if len(candidates):
            candidate = tuple(map(int, candidates[len(candidates) // 2]))
            if candidate not in selected:
                selected.append(candidate)
    return selected


def _fallback_camera(layout: ObservationPointLayout, target: np.ndarray):
    return min(
        layout.camera_layout.cameras,
        key=lambda camera: np.linalg.norm(
            np.asarray((camera.position.x_m, camera.position.y_m, camera.position.z_m))
            - target
        ),
    )


# 保存済み可視グリッドの代表点を解析的視線判定で再計算する．
def validate_visibility_samples(
    environment_case: EnvironmentCase,
    layout: ObservationPointLayout,
    visibility_map: VisibilityMap,
    config: VisibilityConfig | None = None,
) -> tuple[Phase7VisibilitySample, ...]:
    resolved_config = config or VisibilityConfig()
    raycast = AnalyticRaycastBackend(
        environment_case, sample_step_m=resolved_config.ray_sample_step_m
    )
    index = _build_layout_index(layout)
    failures = tuple(VisibilityFailure)
    samples = []
    for y_index, x_index in _representative_cells(visibility_map):
        x_m = float(visibility_map.x_centers_m[x_index])
        y_m = float(visibility_map.y_centers_m[y_index])
        ground_z_m = environment_case.heightmap.surface_elevation_at(x_m, y_m)
        state = GroundTruthState(
            timestamp_s=0.0,
            truth_id="phase7-validation-target",
            position=Position3D(x_m=x_m, y_m=y_m, z_m=ground_z_m),
        )
        result = _evaluate_target(
            environment_case,
            layout,
            state,
            resolved_config,
            raycast,
            index,
            stop_after_first_success=False,
        )
        recomputed_class = (
            VisibilityClass.FULLY_VISIBLE
            if result.fully_visible_point_count
            else VisibilityClass.NOT_VISIBLE
        )
        expected = VisibilityClass(int(visibility_map.classes[y_index, x_index]))
        expected_binary = (
            VisibilityClass.FULLY_VISIBLE
            if expected is VisibilityClass.FULLY_VISIBLE
            else VisibilityClass.NOT_VISIBLE
        )
        camera = (
            index.cameras[result.best_camera.camera_id]
            if result.best_camera is not None
            else _fallback_camera(layout, np.asarray((x_m, y_m, ground_z_m)))
        )
        origin = (camera.position.x_m, camera.position.y_m, camera.position.z_m)
        target = (x_m, y_m, ground_z_m + resolved_config.deer_height_m)
        expected_failure = failures[int(visibility_map.failure_codes[y_index, x_index])]
        samples.append(
            Phase7VisibilitySample(
                x_m=x_m,
                y_m=y_m,
                ground_z_m=ground_z_m,
                expected_class=expected_binary.name,
                expected_failure=expected_failure.value,
                recomputed_class=recomputed_class.name,
                recomputed_failure=result.primary_failure.value,
                camera_id=camera.camera_id,
                ray_start=origin,
                ray_end=target,
                matches_saved_map=expected_binary is recomputed_class,
            )
        )
    return tuple(samples)


def _route_report(environment_case: EnvironmentCase, route: ResolvedRoute) -> dict[str, object]:
    prohibited = 0
    outside = 0
    for row in route.points.itertuples(index=False):
        try:
            x_index, y_index = environment_case.heightmap.indices_at(row.x_m, row.y_m)
        except IndexError:
            outside += 1
            continue
        if (
            environment_case.traversability is not None
            and environment_case.traversability.values[y_index, x_index]
            == TraversabilityValue.PROHIBITED
        ):
            prohibited += 1
    return {
        "route_id": route.definition.route_id,
        "method": route.definition.method,
        "point_count": len(route.points),
        "length_m": route.length_m,
        "outside_terrain_point_count": outside,
        "prohibited_point_count": prohibited,
        "warnings": list(route.warnings),
    }


def _representative_route_observations(
    environment_case: EnvironmentCase,
    layout: ObservationPointLayout,
    route: ResolvedRoute,
    config: VisibilityConfig,
    *,
    sample_count: int = 24,
) -> dict[str, object]:
    indices = np.unique(np.linspace(0, len(route.points) - 1, sample_count, dtype=int))
    frames = []
    for frame_index, point_index in enumerate(indices):
        row = route.points.iloc[int(point_index)]
        frames.append(
            GroundTruthFrame(
                timestamp_s=float(frame_index),
                states=(
                    GroundTruthState(
                        timestamp_s=float(frame_index),
                        truth_id="phase7-validation-deer",
                        position=Position3D(
                            x_m=float(row.x_m),
                            y_m=float(row.y_m),
                            z_m=float(row.z_m),
                        ),
                    ),
                ),
            )
        )
    result = generate_observations(environment_case, layout, tuple(frames), config)
    counts = [len(frame.observations) for frame in result.frames]
    return {
        "route_id": route.definition.route_id,
        "ground_truth_frame_count": len(frames),
        "observation_count": sum(counts),
        "observed_frame_count": sum(count > 0 for count in counts),
        "unobserved_frame_count": sum(count == 0 for count in counts),
    }


# Phase 7のCase・配置・可視結果・ルートを一つの検証記録へまとめる．
def build_phase7_validation_report(
    environment_case: EnvironmentCase,
    layout: ObservationPointLayout,
    visibility_map: VisibilityMap,
    routes: tuple[ResolvedRoute, ...],
    config: VisibilityConfig | None = None,
) -> dict[str, object]:
    resolved_config = config or VisibilityConfig()
    samples = validate_visibility_samples(
        environment_case, layout, visibility_map, resolved_config
    )
    route_reports = [_route_report(environment_case, route) for route in routes]
    observation_report = (
        _representative_route_observations(
            environment_case, layout, routes[0], resolved_config
        )
        if routes
        else None
    )
    failures = []
    if any(not sample.matches_saved_map for sample in samples):
        failures.append("saved visibility map differs from representative recomputation")
    if any(item["outside_terrain_point_count"] for item in route_reports):
        failures.append("route contains points outside terrain")
    if any(item["prohibited_point_count"] for item in route_reports):
        failures.append("route contains prohibited points")
    return {
        "schema_version": "1.0",
        "case_id": environment_case.case_spec.case_id,
        "layout_id": layout.layout_id,
        "status": "passed" if not failures else "failed",
        "failures": failures,
        "environment": {
            "forest_feature_count": len(environment_case.forest.features)
            if environment_case.forest is not None
            else 0,
            "building_feature_count": len(environment_case.buildings.features)
            if environment_case.buildings is not None
            else 0,
        },
        "infrastructure": {
            "observation_point_count": len(layout.points),
            "camera_count": len(layout.camera_layout.cameras),
            "optical_frame_source": "CameraSpec",
            "self_occlusion_policy": "owning pole and housing are excluded from analytic rays",
        },
        "visibility": visibility_map_metrics(visibility_map),
        "representative_visibility_samples": [asdict(sample) for sample in samples],
        "routes": route_reports,
        "representative_route_observations": observation_report,
    }


def save_phase7_validation_report(
    cases_root: str | Path,
    report: dict[str, object],
) -> Path:
    case_directory = resolve_case_path(cases_root, str(report["case_id"]))
    layout_id = str(report["layout_id"])
    destination = (
        case_directory / "previews" / f"genesis_validation_report-{layout_id}.json"
    )
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_name(f".{destination.name}.tmp")
    temporary.write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    temporary.replace(destination)
    latest = case_directory / "previews" / "genesis_validation_report.json"
    latest_temporary = latest.with_name(f".{latest.name}.tmp")
    latest_temporary.write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    latest_temporary.replace(latest)
    return destination
