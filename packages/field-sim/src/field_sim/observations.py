from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from enum import Enum, IntEnum
from math import atan2
from pathlib import Path

import numpy as np
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
from shapely.geometry import Point
from shepherd_contracts import (
    AgeClass,
    CameraSpec,
    GroundTruthFrame,
    GroundTruthState,
    Observation,
    ObservationFrame,
    ObservationPointLayout,
    Position2D,
    Position3D,
)

from field_environment import EnvironmentCase

from .occlusion import AnalyticRaycastBackend, OcclusionKind


class ObservationRule(str, Enum):
    FULL_BODY = "full_body"
    UPPER_BODY = "upper_body"
    ANY_PART = "any_part"


class VisibilityFailure(str, Enum):
    NONE = "NONE"
    OUT_OF_RANGE = "OUT_OF_RANGE"
    OUTSIDE_HORIZONTAL_FOV = "OUTSIDE_HORIZONTAL_FOV"
    OUTSIDE_VERTICAL_FOV = "OUTSIDE_VERTICAL_FOV"
    TERRAIN_OCCLUSION = "TERRAIN_OCCLUSION"
    FOREST_OCCLUSION = "FOREST_OCCLUSION"
    BUILDING_OCCLUSION = "BUILDING_OCCLUSION"


class VisibilityClass(IntEnum):
    OUTSIDE_AREA = 0
    NOT_VISIBLE = 1
    PARTIALLY_VISIBLE = 2
    FULLY_VISIBLE = 3


class VisibilityConfig(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, allow_inf_nan=False)

    deer_height_m: float = Field(default=1.5, gt=0.0)
    sample_heights_m: tuple[float, ...] = (0.0, 0.75, 1.5)
    observation_rule: ObservationRule = ObservationRule.FULL_BODY
    ray_sample_step_m: float = Field(default=0.5, gt=0.0)
    ray_epsilon_m: float = Field(default=0.05, gt=0.0)
    include_age_class: bool = False

    @field_validator("sample_heights_m")
    @classmethod
    def validate_sample_heights(cls, values: tuple[float, ...]) -> tuple[float, ...]:
        if not values:
            raise ValueError("at least one body sample height is required")
        if any(value < 0.0 for value in values):
            raise ValueError("body sample heights cannot be negative")
        if any(current <= previous for previous, current in zip(values, values[1:])):
            raise ValueError("body sample heights must be strictly increasing")
        return values

    @model_validator(mode="after")
    def validate_body_height(self) -> "VisibilityConfig":
        if self.sample_heights_m[-1] > self.deer_height_m:
            raise ValueError("body sample height cannot exceed deer_height_m")
        return self


@dataclass(frozen=True)
class BodySampleVisibility:
    height_m: float
    visible: bool
    failure: VisibilityFailure


@dataclass(frozen=True)
class CameraVisibility:
    camera_id: str
    body_samples: tuple[BodySampleVisibility, ...]
    horizontal_angle_rad: float

    @property
    def visible_sample_count(self) -> int:
        return sum(sample.visible for sample in self.body_samples)

    @property
    def fully_visible(self) -> bool:
        return self.visible_sample_count == len(self.body_samples)


@dataclass(frozen=True)
class TargetVisibility:
    selected_cameras: tuple[CameraVisibility, ...]
    best_camera: CameraVisibility | None
    fully_visible_point_count: int
    partially_visible_point_count: int
    primary_failure: VisibilityFailure


@dataclass(frozen=True)
class ObservationResult:
    frames: tuple[ObservationFrame, ...]
    layout: ObservationPointLayout
    config: VisibilityConfig


@dataclass(frozen=True)
class VisibilityMap:
    x_centers_m: np.ndarray
    y_centers_m: np.ndarray
    classes: np.ndarray
    observing_point_counts: np.ndarray
    visible_sample_counts: np.ndarray
    failure_codes: np.ndarray
    cell_size_m: float

    def __post_init__(self) -> None:
        expected = (len(self.y_centers_m), len(self.x_centers_m))
        for values in (
            self.classes,
            self.observing_point_counts,
            self.visible_sample_counts,
            self.failure_codes,
        ):
            if values.shape != expected:
                raise ValueError(f"visibility map arrays must have shape {expected}")


def as_binary_visibility_map(visibility_map: VisibilityMap) -> VisibilityMap:
    classes = visibility_map.classes.copy()
    classes[classes == VisibilityClass.PARTIALLY_VISIBLE] = VisibilityClass.NOT_VISIBLE
    return VisibilityMap(
        x_centers_m=visibility_map.x_centers_m,
        y_centers_m=visibility_map.y_centers_m,
        classes=classes,
        observing_point_counts=visibility_map.observing_point_counts,
        visible_sample_counts=visibility_map.visible_sample_counts,
        failure_codes=visibility_map.failure_codes,
        cell_size_m=visibility_map.cell_size_m,
    )


@dataclass(frozen=True)
class _LayoutIndex:
    cameras: dict[str, CameraSpec]
    points: tuple
    point_xy: np.ndarray
    point_max_ranges_m: np.ndarray


def _visibility_signature(
    environment_case: EnvironmentCase,
    layout: ObservationPointLayout,
    config: VisibilityConfig,
) -> str:
    digest = hashlib.sha256()
    digest.update(environment_case.case_spec.model_dump_json().encode("utf-8"))
    digest.update(environment_case.heightmap.values.tobytes())
    digest.update(environment_case.farm_boundary.polygon.wkb)
    for layer in (environment_case.forest, environment_case.buildings):
        if layer is not None:
            digest.update(
                json.dumps(layer.features, sort_keys=True, separators=(",", ":")).encode(
                    "utf-8"
                )
            )
    digest.update(layout.model_dump_json().encode("utf-8"))
    digest.update(config.model_dump_json().encode("utf-8"))
    return digest.hexdigest()


def _build_layout_index(layout: ObservationPointLayout) -> _LayoutIndex:
    cameras = {camera.camera_id: camera for camera in layout.camera_layout.cameras}
    point_xy = np.asarray(
        [(point.position.x_m, point.position.y_m) for point in layout.points],
        dtype=np.float64,
    ).reshape((-1, 2))
    point_max_ranges = np.asarray(
        [max(cameras[camera_id].max_observation_distance_m for camera_id in point.camera_ids) for point in layout.points],
        dtype=np.float64,
    )
    return _LayoutIndex(
        cameras=cameras,
        points=layout.points,
        point_xy=point_xy,
        point_max_ranges_m=point_max_ranges,
    )


def _rotation_matrix(camera: CameraSpec) -> np.ndarray:
    yaw = camera.orientation.yaw_rad
    pitch = camera.orientation.pitch_rad
    roll = camera.orientation.roll_rad
    cos_yaw, sin_yaw = np.cos(yaw), np.sin(yaw)
    cos_pitch, sin_pitch = np.cos(pitch), np.sin(pitch)
    cos_roll, sin_roll = np.cos(roll), np.sin(roll)
    rotate_z = np.array(
        ((cos_yaw, -sin_yaw, 0.0), (sin_yaw, cos_yaw, 0.0), (0.0, 0.0, 1.0))
    )
    rotate_y = np.array(
        ((cos_pitch, 0.0, sin_pitch), (0.0, 1.0, 0.0), (-sin_pitch, 0.0, cos_pitch))
    )
    rotate_x = np.array(
        ((1.0, 0.0, 0.0), (0.0, cos_roll, -sin_roll), (0.0, sin_roll, cos_roll))
    )
    return rotate_z @ rotate_y @ rotate_x


def _failure_from_occlusion(kind: OcclusionKind) -> VisibilityFailure:
    return {
        OcclusionKind.NONE: VisibilityFailure.NONE,
        OcclusionKind.TERRAIN: VisibilityFailure.TERRAIN_OCCLUSION,
        OcclusionKind.FOREST: VisibilityFailure.FOREST_OCCLUSION,
        OcclusionKind.BUILDING: VisibilityFailure.BUILDING_OCCLUSION,
    }[kind]


def _rule_satisfied(
    camera_visibility: CameraVisibility,
    config: VisibilityConfig,
) -> bool:
    visible = [sample.visible for sample in camera_visibility.body_samples]
    if config.observation_rule is ObservationRule.FULL_BODY:
        return all(visible)
    if config.observation_rule is ObservationRule.ANY_PART:
        return any(visible)
    upper = [
        sample.visible
        for sample in camera_visibility.body_samples
        if sample.height_m >= config.deer_height_m / 2.0
    ]
    return bool(upper) and all(upper)


def _ground_position(environment_case: EnvironmentCase, state: GroundTruthState) -> np.ndarray:
    x_m = state.position.x_m
    y_m = state.position.y_m
    if isinstance(state.position, Position3D):
        ground_z_m = state.position.z_m
    else:
        ground_z_m = environment_case.heightmap.surface_elevation_at(x_m, y_m)
    return np.asarray((x_m, y_m, ground_z_m), dtype=np.float64)


# 1台のカメラから鹿の足元・胴体・頭部への視線を個別に評価する．
def evaluate_camera_visibility(
    environment_case: EnvironmentCase,
    camera: CameraSpec,
    state: GroundTruthState,
    config: VisibilityConfig,
    raycast: AnalyticRaycastBackend,
    *,
    ground: np.ndarray | None = None,
    inside_forest: bool | None = None,
) -> CameraVisibility:
    origin = np.asarray(
        (camera.position.x_m, camera.position.y_m, camera.position.z_m), dtype=np.float64
    )
    resolved_ground = (
        _ground_position(environment_case, state) if ground is None else ground
    )
    body_to_world = _rotation_matrix(camera)
    world_to_body = body_to_world.T
    resolved_inside_forest = (
        raycast.point_inside_forest(resolved_ground[0], resolved_ground[1])
        if inside_forest is None
        else inside_forest
    )
    samples = []
    horizontal_angle = 0.0
    for height_m in config.sample_heights_m:
        target = resolved_ground + np.asarray((0.0, 0.0, height_m))
        world_vector = target - origin
        distance_m = float(np.linalg.norm(world_vector))
        body_vector = world_to_body @ world_vector
        horizontal_angle = atan2(float(body_vector[1]), float(body_vector[0]))
        vertical_angle = atan2(float(body_vector[2]), float(body_vector[0]))
        failure = VisibilityFailure.NONE
        if distance_m > camera.max_observation_distance_m:
            failure = VisibilityFailure.OUT_OF_RANGE
        elif body_vector[0] <= 0.0 or abs(horizontal_angle) > camera.horizontal_fov_rad / 2.0:
            failure = VisibilityFailure.OUTSIDE_HORIZONTAL_FOV
        elif abs(vertical_angle) > camera.vertical_fov_rad / 2.0:
            failure = VisibilityFailure.OUTSIDE_VERTICAL_FOV
        elif resolved_inside_forest:
            failure = VisibilityFailure.FOREST_OCCLUSION
        else:
            failure = _failure_from_occlusion(
                raycast.first_occlusion(origin, target, epsilon_m=config.ray_epsilon_m).kind
            )
        samples.append(
            BodySampleVisibility(
                height_m=height_m,
                visible=failure is VisibilityFailure.NONE,
                failure=failure,
            )
        )
    return CameraVisibility(
        camera_id=camera.camera_id,
        body_samples=tuple(samples),
        horizontal_angle_rad=horizontal_angle,
    )


def _evaluate_target(
    environment_case: EnvironmentCase,
    layout: ObservationPointLayout,
    state: GroundTruthState,
    config: VisibilityConfig,
    raycast: AnalyticRaycastBackend,
    layout_index: _LayoutIndex | None = None,
    *,
    stop_after_first_success: bool = False,
) -> TargetVisibility:
    index = layout_index or _build_layout_index(layout)
    cameras = index.cameras
    ground = _ground_position(environment_case, state)
    inside_forest = raycast.point_inside_forest(ground[0], ground[1])
    successful = []
    partial = []
    failures: list[VisibilityFailure] = []
    full_point_count = 0
    partial_point_count = 0
    if not len(index.points):
        return TargetVisibility((), None, 0, 0, VisibilityFailure.OUT_OF_RANGE)
    distances = np.linalg.norm(index.point_xy - ground[:2], axis=1)
    nearby_indices = np.flatnonzero(distances <= index.point_max_ranges_m)
    if stop_after_first_success and len(nearby_indices) > 1:
        nearby_indices = nearby_indices[np.argsort(distances[nearby_indices])]
    for point_index in nearby_indices:
        point = index.points[int(point_index)]
        horizontal_distance = float(distances[point_index])
        point_cameras = [cameras[camera_id] for camera_id in point.camera_ids]
        if not point_cameras:
            continue
        point_results = [
            evaluate_camera_visibility(
                environment_case,
                camera,
                state,
                config,
                raycast,
                ground=ground,
                inside_forest=inside_forest,
            )
            for camera in point_cameras
        ]
        point_results.sort(
            key=lambda result: (-result.visible_sample_count, abs(result.horizontal_angle_rad))
        )
        best = point_results[0]
        failures.extend(sample.failure for sample in best.body_samples if not sample.visible)
        if best.fully_visible:
            full_point_count += 1
        if best.visible_sample_count:
            partial_point_count += 1
            partial.append(best)
        if _rule_satisfied(best, config):
            successful.append(best)
            if stop_after_first_success:
                break
    best_camera = None
    if successful:
        best_camera = max(
            successful,
            key=lambda result: (result.visible_sample_count, -abs(result.horizontal_angle_rad)),
        )
    elif partial:
        partial.sort(key=lambda result: (-result.visible_sample_count, abs(result.horizontal_angle_rad)))
        best_camera = partial[0]
    primary_failure = (
        failures[0]
        if failures
        else (VisibilityFailure.OUT_OF_RANGE if not len(nearby_indices) else VisibilityFailure.NONE)
    )
    return TargetVisibility(
        selected_cameras=tuple(successful),
        best_camera=best_camera,
        fully_visible_point_count=full_point_count,
        partially_visible_point_count=partial_point_count,
        primary_failure=primary_failure,
    )


# Ground Truthから真値IDを含まないPerfect Observationを生成する．
def generate_observations(
    environment_case: EnvironmentCase,
    layout: ObservationPointLayout,
    frames: tuple[GroundTruthFrame, ...],
    config: VisibilityConfig | None = None,
) -> ObservationResult:
    resolved_config = config or VisibilityConfig()
    raycast = AnalyticRaycastBackend(
        environment_case, sample_step_m=resolved_config.ray_sample_step_m
    )
    layout_index = _build_layout_index(layout)
    camera_by_id = layout_index.cameras
    output_frames = []
    for frame_index, frame in enumerate(frames):
        observations = []
        for state in frame.states:
            target_visibility = _evaluate_target(
                environment_case, layout, state, resolved_config, raycast, layout_index
            )
            for selected in target_visibility.selected_cameras:
                camera = camera_by_id[selected.camera_id]
                interval_steps = frame.timestamp_s / camera.observation_interval_s
                if not np.isclose(interval_steps, round(interval_steps), rtol=0.0, atol=1e-9):
                    continue
                observations.append(
                    Observation(
                        timestamp_s=frame.timestamp_s,
                        camera_id=selected.camera_id,
                        observation_id=f"obs-{frame_index:06d}-{len(observations):06d}",
                        position=Position2D(x_m=state.position.x_m, y_m=state.position.y_m),
                        age_class=(
                            state.age_class
                            if resolved_config.include_age_class
                            else AgeClass.UNKNOWN
                        ),
                    )
                )
        output_frames.append(
            ObservationFrame(timestamp_s=frame.timestamp_s, observations=tuple(observations))
        )
    return ObservationResult(
        frames=tuple(output_frames), layout=layout, config=resolved_config
    )


# 鹿の高さ方向の可視性を地面上の2Dグリッドへ投影する．
def compute_visibility_map(
    environment_case: EnvironmentCase,
    layout: ObservationPointLayout,
    config: VisibilityConfig | None = None,
    *,
    cell_size_m: float = 5.0,
    checkpoint_path: str | Path | None = None,
    checkpoint_row_count: int = 8,
    worker_count: int = 1,
    binary_only: bool = False,
) -> VisibilityMap:
    if worker_count <= 0:
        raise ValueError("worker_count must be positive")
    if worker_count > 1 or binary_only:
        from .visibility_grid import compute_visibility_map_grid

        return compute_visibility_map_grid(
            environment_case,
            layout,
            config,
            cell_size_m=cell_size_m,
            checkpoint_path=checkpoint_path,
            row_chunk_size=checkpoint_row_count,
            worker_count=worker_count,
            binary_only=binary_only,
        )
    if cell_size_m <= 0.0:
        raise ValueError("cell_size_m must be positive")
    if checkpoint_row_count <= 0:
        raise ValueError("checkpoint_row_count must be positive")
    resolved_config = config or VisibilityConfig()
    bounds = environment_case.farm_boundary.bounds
    x_centers = np.arange(bounds.min_x_m + cell_size_m / 2.0, bounds.max_x_m, cell_size_m)
    y_centers = np.arange(bounds.min_y_m + cell_size_m / 2.0, bounds.max_y_m, cell_size_m)
    shape = (len(y_centers), len(x_centers))
    classes = np.full(shape, VisibilityClass.OUTSIDE_AREA, dtype=np.uint8)
    point_counts = np.zeros(shape, dtype=np.uint16)
    sample_counts = np.zeros(shape, dtype=np.uint8)
    failure_codes = np.zeros(shape, dtype=np.uint8)
    completed_rows = 0
    checkpoint = None if checkpoint_path is None else Path(checkpoint_path)
    signature = _visibility_signature(environment_case, layout, resolved_config)
    if checkpoint is not None and checkpoint.is_file():
        stored = np.load(checkpoint)
        signature_matches = (
            "signature" in stored.files and str(stored["signature"]) == signature
        )
        grid_matches = (
            np.array_equal(stored["x_centers_m"], x_centers)
            and np.array_equal(stored["y_centers_m"], y_centers)
            and np.isclose(float(stored["cell_size_m"]), cell_size_m)
        )
        if signature_matches and grid_matches:
            classes = stored["classes"]
            point_counts = stored["observing_point_counts"]
            sample_counts = stored["visible_sample_counts"]
            failure_codes = stored["failure_codes"]
            completed_rows = int(stored["completed_rows"])
    raycast = AnalyticRaycastBackend(
        environment_case, sample_step_m=resolved_config.ray_sample_step_m
    )
    layout_index = _build_layout_index(layout)
    failure_to_code = {failure: index for index, failure in enumerate(VisibilityFailure)}
    for y_index, y_m in enumerate(y_centers):
        if y_index < completed_rows:
            continue
        for x_index, x_m in enumerate(x_centers):
            if not environment_case.farm_boundary.polygon.covers(
                Point(float(x_m), float(y_m))
            ):
                continue
            try:
                z_m = environment_case.heightmap.surface_elevation_at(float(x_m), float(y_m))
            except IndexError:
                continue
            state = GroundTruthState(
                timestamp_s=0.0,
                truth_id="visibility-map-target",
                position=Position3D(x_m=float(x_m), y_m=float(y_m), z_m=z_m),
            )
            visibility = _evaluate_target(
                environment_case, layout, state, resolved_config, raycast, layout_index
            )
            selected = visibility.best_camera
            visible_count = 0 if selected is None else selected.visible_sample_count
            sample_counts[y_index, x_index] = visible_count
            point_counts[y_index, x_index] = visibility.fully_visible_point_count
            failure_codes[y_index, x_index] = failure_to_code[visibility.primary_failure]
            if visibility.fully_visible_point_count:
                classes[y_index, x_index] = VisibilityClass.FULLY_VISIBLE
            elif visible_count:
                classes[y_index, x_index] = VisibilityClass.PARTIALLY_VISIBLE
            else:
                classes[y_index, x_index] = VisibilityClass.NOT_VISIBLE
        if checkpoint is not None and (
            (y_index + 1) % checkpoint_row_count == 0 or y_index + 1 == len(y_centers)
        ):
            checkpoint.parent.mkdir(parents=True, exist_ok=True)
            temporary = checkpoint.with_name(f".{checkpoint.name}.tmp")
            with temporary.open("wb") as stream:
                np.savez_compressed(
                    stream,
                    x_centers_m=x_centers,
                    y_centers_m=y_centers,
                    classes=classes,
                    observing_point_counts=point_counts,
                    visible_sample_counts=sample_counts,
                    failure_codes=failure_codes,
                    completed_rows=np.asarray(y_index + 1),
                    cell_size_m=np.asarray(cell_size_m),
                    signature=np.asarray(signature),
                )
            temporary.replace(checkpoint)
    return VisibilityMap(
        x_centers_m=x_centers,
        y_centers_m=y_centers,
        classes=classes,
        observing_point_counts=point_counts,
        visible_sample_counts=sample_counts,
        failure_codes=failure_codes,
        cell_size_m=cell_size_m,
    )


def load_visibility_map(path: str | Path) -> VisibilityMap:
    stored = np.load(Path(path))
    return VisibilityMap(
        x_centers_m=stored["x_centers_m"],
        y_centers_m=stored["y_centers_m"],
        classes=stored["classes"],
        observing_point_counts=stored["observing_point_counts"],
        visible_sample_counts=stored["visible_sample_counts"],
        failure_codes=stored["failure_codes"],
        cell_size_m=float(stored["cell_size_m"]),
    )


def _largest_connected_cell_count(mask: np.ndarray) -> int:
    visited = np.zeros(mask.shape, dtype=bool)
    largest = 0
    for start_y, start_x in np.argwhere(mask):
        if visited[start_y, start_x]:
            continue
        stack = [(int(start_y), int(start_x))]
        visited[start_y, start_x] = True
        count = 0
        while stack:
            y_index, x_index = stack.pop()
            count += 1
            for next_y, next_x in (
                (y_index - 1, x_index),
                (y_index + 1, x_index),
                (y_index, x_index - 1),
                (y_index, x_index + 1),
            ):
                if (
                    0 <= next_y < mask.shape[0]
                    and 0 <= next_x < mask.shape[1]
                    and mask[next_y, next_x]
                    and not visited[next_y, next_x]
                ):
                    visited[next_y, next_x] = True
                    stack.append((next_y, next_x))
        largest = max(largest, count)
    return largest


def visibility_map_metrics(visibility_map: VisibilityMap) -> dict[str, object]:
    inside = visibility_map.classes != VisibilityClass.OUTSIDE_AREA
    inside_count = int(inside.sum())
    counts = {
        visibility_class.name.lower(): int(
            (visibility_map.classes == visibility_class).sum()
        )
        for visibility_class in (
            VisibilityClass.NOT_VISIBLE,
            VisibilityClass.PARTIALLY_VISIBLE,
            VisibilityClass.FULLY_VISIBLE,
        )
    }
    failure_counts = {
        failure.value: int(
            np.logical_and(inside, visibility_map.failure_codes == index).sum()
        )
        for index, failure in enumerate(VisibilityFailure)
    }
    largest_hidden_cells = _largest_connected_cell_count(
        visibility_map.classes == VisibilityClass.NOT_VISIBLE
    )
    return {
        "cell_size_m": visibility_map.cell_size_m,
        "evaluated_cell_count": inside_count,
        "evaluated_horizontal_area_m2": inside_count * visibility_map.cell_size_m**2,
        "class_counts": counts,
        "class_rates": {
            name: (count / inside_count if inside_count else 0.0)
            for name, count in counts.items()
        },
        "multiple_fully_observing_point_rate": (
            float(np.logical_and(inside, visibility_map.observing_point_counts >= 2).sum())
            / inside_count
            if inside_count
            else 0.0
        ),
        "largest_connected_not_visible_area_m2": (
            largest_hidden_cells * visibility_map.cell_size_m**2
        ),
        "primary_failure_counts": failure_counts,
    }


def save_visibility_map_metrics(
    path: str | Path,
    visibility_map: VisibilityMap,
) -> Path:
    destination = Path(path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(
        json.dumps(visibility_map_metrics(visibility_map), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return destination
