from __future__ import annotations

import json
from math import atan2, pi
from pathlib import Path

import numpy as np
from pydantic import BaseModel, ConfigDict, Field
from shapely import contains_xy
from shapely.geometry import GeometryCollection, Point, shape
from shapely.ops import unary_union

from field_environment import (
    EnvironmentCase,
    FeatureLayerStatus,
    resolve_case_path,
    validate_case_id,
)
from shepherd_contracts import (
    DEFAULT_MAX_OBSERVATION_DISTANCE_M,
    CameraLayout,
    CameraOrientation,
    CameraSpec,
    ObservationPointLayout,
    ObservationPointSpec,
    Position3D,
)


class ObservationPointPlacement(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, allow_inf_nan=False)

    point_id: str = Field(min_length=1)
    x_m: float
    y_m: float


class CameraMountProfile(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, allow_inf_nan=False)

    profile_id: str = Field(min_length=1)
    pole_height_m: float = Field(default=5.0, gt=0.0)
    camera_count: int = Field(default=6, ge=1, le=64)
    horizontal_fov_rad: float = Field(default=pi / 3.0, gt=0.0, le=2.0 * pi)
    vertical_fov_rad: float = Field(default=0.8377580409572781, gt=0.0, le=pi)
    max_observation_distance_m: float = Field(
        default=DEFAULT_MAX_OBSERVATION_DISTANCE_M, gt=0.0
    )
    observation_interval_s: float = Field(default=1.0, gt=0.0)
    first_yaw_rad: float = Field(default=0.0, ge=-pi, le=pi)
    pitch_rad: float | None = Field(default=None, ge=-pi / 2.0, le=pi / 2.0)
    pitch_target_height_m: float = Field(default=0.75, ge=0.0)
    pitch_reference_distance_m: float = Field(default=20.0, gt=0.0)

    @property
    def resolved_pitch_rad(self) -> float:
        if self.pitch_rad is not None:
            return self.pitch_rad
        return atan2(
            self.pole_height_m - self.pitch_target_height_m,
            self.pitch_reference_distance_m,
        )


def _normalize_yaw(yaw_rad: float) -> float:
    normalized = (yaw_rad + pi) % (2.0 * pi) - pi
    return pi if np.isclose(normalized, -pi) else float(normalized)


def _allowed_geometry(environment_case: EnvironmentCase):
    geometry = environment_case.farm_boundary.polygon
    for layer in (environment_case.forest, environment_case.buildings):
        if layer is not None and layer.status is FeatureLayerStatus.AVAILABLE:
            obstacle = unary_union([shape(feature["geometry"]) for feature in layer.features])
            geometry = geometry.difference(obstacle)
    return geometry


def _mesh_surface_contains(environment_case: EnvironmentCase, x_m: float, y_m: float) -> bool:
    try:
        environment_case.heightmap.surface_elevation_at(x_m, y_m)
    except IndexError:
        return False
    return True


# 40 m正方格子の中心から，牧場内かつ森林・建物外の観測点を作る．
def generate_grid_observation_points(
    environment_case: EnvironmentCase,
    *,
    spacing_m: float = 40.0,
    point_id_prefix: str = "grid40",
) -> tuple[ObservationPointPlacement, ...]:
    if spacing_m <= 0.0:
        raise ValueError("spacing_m must be positive")
    allowed = _allowed_geometry(environment_case)
    min_x, min_y, max_x, max_y = environment_case.farm_boundary.polygon.bounds
    x_values = np.arange(min_x + spacing_m / 2.0, max_x, spacing_m)
    y_values = np.arange(min_y + spacing_m / 2.0, max_y, spacing_m)
    placements = []
    for row, y_m in enumerate(y_values):
        for column, x_m in enumerate(x_values):
            if not allowed.covers(Point(float(x_m), float(y_m))):
                continue
            if not _mesh_surface_contains(environment_case, float(x_m), float(y_m)):
                continue
            placements.append(
                ObservationPointPlacement(
                    point_id=f"{point_id_prefix}-r{row:03d}c{column:03d}",
                    x_m=float(x_m),
                    y_m=float(y_m),
                )
            )
    return tuple(placements)


def _van_der_corput(indices: np.ndarray, base: int) -> np.ndarray:
    values = np.zeros(len(indices), dtype=np.float64)
    denominator = 1.0
    working = indices.copy()
    while np.any(working):
        denominator *= base
        working, remainder = np.divmod(working, base)
        values += remainder / denominator
    return values


# 候補点から最大最小距離法で，決められた個数の等分散観測点を選ぶ．
def generate_uniform_observation_points(
    environment_case: EnvironmentCase,
    *,
    point_count: int,
    point_id_prefix: str = "uniform",
) -> tuple[ObservationPointPlacement, ...]:
    if point_count <= 0:
        raise ValueError("point_count must be positive")
    allowed = _allowed_geometry(environment_case)
    if allowed.is_empty or isinstance(allowed, GeometryCollection):
        raise ValueError("Case has no area available for observation points")
    min_x, min_y, max_x, max_y = environment_case.farm_boundary.polygon.bounds
    candidate_target = max(point_count * 3, point_count + 32)
    batch_size = max(candidate_target * 2, 256)
    accepted: list[np.ndarray] = []
    next_index = 1
    accepted_count = 0
    for _ in range(20):
        indices = np.arange(next_index, next_index + batch_size, dtype=np.int64)
        next_index += batch_size
        x_values = min_x + _van_der_corput(indices, 2) * (max_x - min_x)
        y_values = min_y + _van_der_corput(indices, 3) * (max_y - min_y)
        mask = contains_xy(allowed, x_values, y_values)
        candidates = np.column_stack((x_values[mask], y_values[mask]))
        if len(candidates):
            surface_mask = np.asarray(
                [
                    _mesh_surface_contains(environment_case, float(x_m), float(y_m))
                    for x_m, y_m in candidates
                ],
                dtype=bool,
            )
            accepted.append(candidates[surface_mask])
            accepted_count += int(surface_mask.sum())
        if accepted_count >= candidate_target:
            break
    if accepted_count < point_count:
        raise ValueError("not enough valid area to generate the requested observation points")
    candidates = np.vstack(accepted)[:candidate_target]
    center = np.asarray(allowed.centroid.coords[0], dtype=np.float64)
    selected_indices = [int(np.argmin(np.linalg.norm(candidates - center, axis=1)))]
    minimum_distance_squared = np.sum(
        (candidates - candidates[selected_indices[0]]) ** 2, axis=1
    )
    minimum_distance_squared[selected_indices[0]] = -1.0
    while len(selected_indices) < point_count:
        selected = int(np.argmax(minimum_distance_squared))
        selected_indices.append(selected)
        distances = np.sum((candidates - candidates[selected]) ** 2, axis=1)
        minimum_distance_squared = np.minimum(minimum_distance_squared, distances)
        minimum_distance_squared[selected_indices] = -1.0
    selected_points = candidates[np.asarray(selected_indices)]
    return tuple(
        ObservationPointPlacement(
            point_id=f"{point_id_prefix}-{index + 1:04d}",
            x_m=float(x_m),
            y_m=float(y_m),
        )
        for index, (x_m, y_m) in enumerate(selected_points)
    )


# 観測点の台数指定から固定カメラ群の向きとCameraLayoutを解決する．
def create_observation_point_layout(
    environment_case: EnvironmentCase,
    placements: tuple[ObservationPointPlacement, ...] | list[ObservationPointPlacement],
    mount_profile: CameraMountProfile,
    *,
    layout_id: str,
    placement_method: str,
) -> ObservationPointLayout:
    validate_case_id(layout_id)
    cameras = []
    points = []
    pitch_rad = mount_profile.resolved_pitch_rad
    for placement in placements:
        ground_z_m = environment_case.heightmap.surface_elevation_at(
            placement.x_m, placement.y_m
        )
        position = Position3D(
            x_m=placement.x_m,
            y_m=placement.y_m,
            z_m=ground_z_m + mount_profile.pole_height_m,
        )
        camera_ids = []
        for camera_index in range(mount_profile.camera_count):
            camera_id = f"{placement.point_id}-cam-{camera_index + 1:02d}"
            camera_ids.append(camera_id)
            yaw_rad = _normalize_yaw(
                mount_profile.first_yaw_rad
                + camera_index * 2.0 * pi / mount_profile.camera_count
            )
            cameras.append(
                CameraSpec(
                    camera_id=camera_id,
                    position=position,
                    orientation=CameraOrientation(
                        yaw_rad=yaw_rad,
                        pitch_rad=pitch_rad,
                        roll_rad=0.0,
                    ),
                    horizontal_fov_rad=mount_profile.horizontal_fov_rad,
                    vertical_fov_rad=mount_profile.vertical_fov_rad,
                    max_observation_distance_m=mount_profile.max_observation_distance_m,
                    observation_interval_s=mount_profile.observation_interval_s,
                )
            )
        points.append(
            ObservationPointSpec(
                point_id=placement.point_id,
                position=position,
                camera_ids=tuple(camera_ids),
            )
        )
    camera_layout = CameraLayout(layout_id=f"{layout_id}-cameras", cameras=tuple(cameras))
    return ObservationPointLayout(
        layout_id=layout_id,
        points=tuple(points),
        camera_layout=camera_layout,
        metadata={
            "placement_method": placement_method,
            "mount_profile": mount_profile.model_dump(mode="json"),
            "resolved_pitch_rad": pitch_rad,
            "point_count": len(points),
            "camera_count": len(cameras),
        },
    )


def create_default_observation_point_layouts(
    environment_case: EnvironmentCase,
    mount_profile: CameraMountProfile,
    *,
    grid_spacing_m: float = 40.0,
) -> tuple[ObservationPointLayout, ObservationPointLayout]:
    grid_points = generate_grid_observation_points(
        environment_case, spacing_m=grid_spacing_m
    )
    if not grid_points:
        raise ValueError("40 m grid produced no valid observation points")
    uniform_points = generate_uniform_observation_points(
        environment_case, point_count=len(grid_points)
    )
    suffix = f"cam{mount_profile.camera_count}"
    grid_layout = create_observation_point_layout(
        environment_case,
        grid_points,
        mount_profile,
        layout_id=f"default-grid40-{suffix}",
        placement_method="farm 40 m grid cell centers; forest and buildings excluded",
    )
    grid_layout = grid_layout.model_copy(
        update={
            "metadata": {
                **grid_layout.metadata,
                "grid_spacing_m": grid_spacing_m,
                "grid_spacing_rationale": (
                    "42 m nominal deer observation distance rounded to a manageable 40 m grid; "
                    "this is an experiment assumption, not verified hardware performance"
                ),
            }
        }
    )
    uniform_layout = create_observation_point_layout(
        environment_case,
        uniform_points,
        mount_profile,
        layout_id=f"default-uniform-{suffix}",
        placement_method="deterministic maximin distribution with grid40-equivalent count",
    )
    return grid_layout, uniform_layout


def save_observation_point_layout(
    cases_root: str | Path,
    case_id: str,
    layout: ObservationPointLayout,
    *,
    overwrite: bool = False,
) -> Path:
    case_directory = resolve_case_path(cases_root, case_id)
    layout_id = validate_case_id(layout.layout_id)
    destination = case_directory / "observation_point_layouts" / layout_id / "layout.json"
    if destination.exists() and not overwrite:
        raise FileExistsError(f"ObservationPointLayout already exists: {destination}")
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_name(".layout.json.tmp")
    temporary.write_text(layout.model_dump_json(indent=2), encoding="utf-8")
    temporary.replace(destination)
    generation = {
        "schema_version": "1.0",
        "layout_id": layout.layout_id,
        "placement_method": layout.metadata.get("placement_method"),
        "generator": layout.metadata.get("generator"),
        "generator_seed": layout.metadata.get("generator_seed"),
        "parent_layout_id": layout.metadata.get("parent_layout_id"),
        "point_count": len(layout.points),
        "camera_count": len(layout.camera_layout.cameras),
        "parameters": layout.metadata.get("parameters", {}),
        "mount_profile": layout.metadata.get("mount_profile", {}),
    }
    (destination.parent / "generation.json").write_text(
        json.dumps(generation, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return destination


def load_observation_point_layout(
    cases_root: str | Path,
    case_id: str,
    layout_id: str,
) -> ObservationPointLayout:
    case_directory = resolve_case_path(cases_root, case_id)
    validated_layout_id = validate_case_id(layout_id)
    path = case_directory / "observation_point_layouts" / validated_layout_id / "layout.json"
    return ObservationPointLayout.model_validate_json(path.read_text(encoding="utf-8"))
