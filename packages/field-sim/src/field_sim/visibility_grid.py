from __future__ import annotations

from concurrent.futures import ProcessPoolExecutor
from pathlib import Path
from typing import Iterator

import numpy as np
from shapely import intersects_xy
from shepherd_contracts import GroundTruthState, ObservationPointLayout, Position3D

from field_environment import EnvironmentCase

from .observations import (
    VisibilityClass,
    VisibilityConfig,
    VisibilityFailure,
    VisibilityMap,
    _build_layout_index,
    _evaluate_target,
    _visibility_signature,
)
from .occlusion import AnalyticRaycastBackend


_WORKER_ENVIRONMENT: EnvironmentCase | None = None
_WORKER_LAYOUT: ObservationPointLayout | None = None
_WORKER_CONFIG: VisibilityConfig | None = None
_WORKER_RAYCAST: AnalyticRaycastBackend | None = None
_WORKER_LAYOUT_INDEX = None
_WORKER_X_CENTERS: np.ndarray | None = None
_WORKER_BINARY_ONLY = False


def _initialize_worker(
    environment_case: EnvironmentCase,
    layout: ObservationPointLayout,
    config: VisibilityConfig,
    x_centers: np.ndarray,
    binary_only: bool,
) -> None:
    global _WORKER_ENVIRONMENT
    global _WORKER_LAYOUT
    global _WORKER_CONFIG
    global _WORKER_RAYCAST
    global _WORKER_LAYOUT_INDEX
    global _WORKER_X_CENTERS
    global _WORKER_BINARY_ONLY

    _WORKER_ENVIRONMENT = environment_case
    _WORKER_LAYOUT = layout
    _WORKER_CONFIG = config
    _WORKER_RAYCAST = AnalyticRaycastBackend(
        environment_case, sample_step_m=config.ray_sample_step_m
    )
    _WORKER_LAYOUT_INDEX = _build_layout_index(layout)
    _WORKER_X_CENTERS = x_centers
    _WORKER_BINARY_ONLY = binary_only


def _row_chunks(start: int, stop: int, size: int) -> Iterator[tuple[int, int]]:
    for chunk_start in range(start, stop, size):
        yield chunk_start, min(chunk_start + size, stop)


def _evaluate_rows(task: tuple[int, np.ndarray]):
    start_index, y_values = task
    if (
        _WORKER_ENVIRONMENT is None
        or _WORKER_LAYOUT is None
        or _WORKER_CONFIG is None
        or _WORKER_RAYCAST is None
        or _WORKER_X_CENTERS is None
    ):
        raise RuntimeError("visibility worker is not initialized")

    shape = (len(y_values), len(_WORKER_X_CENTERS))
    classes = np.full(shape, VisibilityClass.OUTSIDE_AREA, dtype=np.uint8)
    point_counts = np.zeros(shape, dtype=np.uint16)
    sample_counts = np.zeros(shape, dtype=np.uint8)
    failure_codes = np.zeros(shape, dtype=np.uint8)
    failure_to_code = {failure: index for index, failure in enumerate(VisibilityFailure)}
    x_grid, y_grid = np.meshgrid(_WORKER_X_CENTERS, y_values)
    inside = intersects_xy(_WORKER_ENVIRONMENT.farm_boundary.polygon, x_grid, y_grid)

    for local_y, y_m in enumerate(y_values):
        for x_index in np.flatnonzero(inside[local_y]):
            x_m = float(_WORKER_X_CENTERS[x_index])
            try:
                z_m = _WORKER_ENVIRONMENT.heightmap.surface_elevation_at(x_m, float(y_m))
            except IndexError:
                continue
            state = GroundTruthState(
                timestamp_s=0.0,
                truth_id="visibility-map-target",
                position=Position3D(x_m=x_m, y_m=float(y_m), z_m=z_m),
            )
            visibility = _evaluate_target(
                _WORKER_ENVIRONMENT,
                _WORKER_LAYOUT,
                state,
                _WORKER_CONFIG,
                _WORKER_RAYCAST,
                _WORKER_LAYOUT_INDEX,
                stop_after_first_success=_WORKER_BINARY_ONLY,
            )
            selected = visibility.best_camera
            visible_count = 0 if selected is None else selected.visible_sample_count
            sample_counts[local_y, x_index] = visible_count
            point_counts[local_y, x_index] = visibility.fully_visible_point_count
            failure_codes[local_y, x_index] = failure_to_code[visibility.primary_failure]
            if visibility.fully_visible_point_count:
                classes[local_y, x_index] = VisibilityClass.FULLY_VISIBLE
            elif visible_count and not _WORKER_BINARY_ONLY:
                classes[local_y, x_index] = VisibilityClass.PARTIALLY_VISIBLE
            else:
                classes[local_y, x_index] = VisibilityClass.NOT_VISIBLE
    return start_index, classes, point_counts, sample_counts, failure_codes


def _save_checkpoint(
    path: Path,
    *,
    x_centers: np.ndarray,
    y_centers: np.ndarray,
    classes: np.ndarray,
    point_counts: np.ndarray,
    sample_counts: np.ndarray,
    failure_codes: np.ndarray,
    completed_rows: int,
    cell_size_m: float,
    signature: str,
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp")
    with temporary.open("wb") as stream:
        np.savez_compressed(
            stream,
            x_centers_m=x_centers,
            y_centers_m=y_centers,
            classes=classes,
            observing_point_counts=point_counts,
            visible_sample_counts=sample_counts,
            failure_codes=failure_codes,
            completed_rows=np.asarray(completed_rows),
            cell_size_m=np.asarray(cell_size_m),
            signature=np.asarray(signature),
        )
    temporary.replace(path)


# 1 m可視評価を行ブロックへ分割し，複数CPUで再開可能に計算する．
def compute_visibility_map_grid(
    environment_case: EnvironmentCase,
    layout: ObservationPointLayout,
    config: VisibilityConfig | None = None,
    *,
    cell_size_m: float,
    checkpoint_path: str | Path | None,
    row_chunk_size: int,
    worker_count: int,
    binary_only: bool,
) -> VisibilityMap:
    if cell_size_m <= 0.0:
        raise ValueError("cell_size_m must be positive")
    if row_chunk_size <= 0:
        raise ValueError("row_chunk_size must be positive")
    if worker_count <= 0:
        raise ValueError("worker_count must be positive")

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
    mode = "binary" if binary_only else "detailed"
    signature = f"{_visibility_signature(environment_case, layout, resolved_config)}:{mode}:v1"

    if checkpoint is not None and checkpoint.is_file():
        with np.load(checkpoint) as stored:
            signature_matches = (
                "signature" in stored.files and str(stored["signature"]) == signature
            )
            grid_matches = (
                np.array_equal(stored["x_centers_m"], x_centers)
                and np.array_equal(stored["y_centers_m"], y_centers)
                and np.isclose(float(stored["cell_size_m"]), cell_size_m)
            )
            if signature_matches and grid_matches:
                classes = stored["classes"].copy()
                point_counts = stored["observing_point_counts"].copy()
                sample_counts = stored["visible_sample_counts"].copy()
                failure_codes = stored["failure_codes"].copy()
                completed_rows = int(stored["completed_rows"])

    tasks = [
        (start, y_centers[start:stop])
        for start, stop in _row_chunks(completed_rows, len(y_centers), row_chunk_size)
    ]
    initializer_args = (
        environment_case,
        layout,
        resolved_config,
        x_centers,
        binary_only,
    )
    if worker_count == 1:
        _initialize_worker(*initializer_args)
        results = map(_evaluate_rows, tasks)
        executor = None
    else:
        executor = ProcessPoolExecutor(
            max_workers=worker_count,
            initializer=_initialize_worker,
            initargs=initializer_args,
        )
        results = executor.map(_evaluate_rows, tasks, chunksize=1)

    try:
        for start, chunk_classes, chunk_points, chunk_samples, chunk_failures in results:
            stop = start + len(chunk_classes)
            classes[start:stop] = chunk_classes
            point_counts[start:stop] = chunk_points
            sample_counts[start:stop] = chunk_samples
            failure_codes[start:stop] = chunk_failures
            if checkpoint is not None:
                _save_checkpoint(
                    checkpoint,
                    x_centers=x_centers,
                    y_centers=y_centers,
                    classes=classes,
                    point_counts=point_counts,
                    sample_counts=sample_counts,
                    failure_codes=failure_codes,
                    completed_rows=stop,
                    cell_size_m=cell_size_m,
                    signature=signature,
                )
    finally:
        if executor is not None:
            executor.shutdown()

    return VisibilityMap(
        x_centers_m=x_centers,
        y_centers_m=y_centers,
        classes=classes,
        observing_point_counts=point_counts,
        visible_sample_counts=sample_counts,
        failure_codes=failure_codes,
        cell_size_m=cell_size_m,
    )
