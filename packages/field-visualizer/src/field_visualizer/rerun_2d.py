from __future__ import annotations

from collections.abc import Iterable
from pathlib import Path

import numpy as np
from shapely.geometry import Polygon, MultiPolygon, shape
from shepherd_contracts import (
    GroundTruthFrame,
    ObservationFrame,
    ObservationPointLayout,
    TrackingFrame,
)

from field_environment import EnvironmentCase, FeatureLayerStatus


def _rerun():
    try:
        import rerun as rr
    except ImportError as error:
        raise RuntimeError(
            "Rerun visualization requires `pip install 'field-visualizer[rerun]'`"
        ) from error
    return rr


def _polygon_lines(geometry) -> list[np.ndarray]:
    polygons = [geometry] if isinstance(geometry, Polygon) else list(geometry.geoms)
    lines = []
    for polygon in polygons:
        lines.append(np.asarray(polygon.exterior.coords, dtype=float))
        lines.extend(np.asarray(interior.coords, dtype=float) for interior in polygon.interiors)
    return lines


def _feature_lines(layer) -> list[np.ndarray]:
    if layer is None or layer.status is not FeatureLayerStatus.AVAILABLE:
        return []
    lines = []
    for feature in layer.features:
        geometry = shape(feature["geometry"])
        if isinstance(geometry, (Polygon, MultiPolygon)):
            lines.extend(_polygon_lines(geometry))
    return lines


# Case，真値，観測，推定TrackをRerunの同一2D時間軸へ記録する．
def log_tracking_replay(
    environment_case: EnvironmentCase,
    *,
    ground_truth_frames: tuple[GroundTruthFrame, ...] = (),
    observation_frames: tuple[ObservationFrame, ...] = (),
    tracking_frames: tuple[TrackingFrame, ...] = (),
    observation_point_layout: ObservationPointLayout | None = None,
    application_id: str = "wildlife-tracking-replay",
    recording_path: str | Path | None = None,
    spawn: bool = False,
) -> None:
    rr = _rerun()
    rr.init(application_id, spawn=spawn)
    if recording_path is not None:
        rr.set_sinks(rr.FileSink(str(recording_path)))
    rr.set_time("simulation_time", duration=0.0)
    terrain_bounds = environment_case.heightmap.bounds
    rr.log(
        "world/terrain_extent",
        rr.LineStrips2D(
            [
                [
                    [terrain_bounds.min_x_m, terrain_bounds.min_y_m],
                    [terrain_bounds.max_x_m, terrain_bounds.min_y_m],
                    [terrain_bounds.max_x_m, terrain_bounds.max_y_m],
                    [terrain_bounds.min_x_m, terrain_bounds.max_y_m],
                    [terrain_bounds.min_x_m, terrain_bounds.min_y_m],
                ]
            ],
            colors=[120, 120, 120],
            radii=1.0,
        ),
        static=True,
    )
    rr.log(
        "world/farm_boundary",
        rr.LineStrips2D(
            _polygon_lines(environment_case.farm_boundary.polygon),
            colors=[255, 0, 0],
            radii=1.5,
        ),
        static=True,
    )
    for name, layer, color in (
        ("forest", environment_case.forest, [30, 120, 30]),
        ("buildings", environment_case.buildings, [230, 140, 40]),
    ):
        lines = _feature_lines(layer)
        if lines:
            rr.log(
                f"world/{name}",
                rr.LineStrips2D(lines, colors=color, radii=0.8),
                static=True,
            )
    if observation_point_layout is not None:
        rr.log(
            "world/observation_points",
            rr.Points2D(
                [
                    [point.position.x_m, point.position.y_m]
                    for point in observation_point_layout.points
                ],
                colors=[30, 80, 255],
                radii=2.0,
                labels=[point.point_id for point in observation_point_layout.points],
            ),
            static=True,
        )
    observations_by_time = {frame.timestamp_s: frame for frame in observation_frames}
    tracking_by_time = {frame.timestamp_s: frame for frame in tracking_frames}
    truth_by_time = {frame.timestamp_s: frame for frame in ground_truth_frames}
    timestamps = sorted(
        set(observations_by_time) | set(tracking_by_time) | set(truth_by_time)
    )
    for timestamp_s in timestamps:
        rr.set_time("simulation_time", duration=float(timestamp_s))
        truth = truth_by_time.get(timestamp_s)
        if truth is not None:
            rr.log(
                "world/ground_truth",
                rr.Points2D(
                    [[state.position.x_m, state.position.y_m] for state in truth.states],
                    colors=[0, 180, 255],
                    radii=2.0,
                    labels=[state.truth_id for state in truth.states],
                ),
            )
        observation = observations_by_time.get(timestamp_s)
        if observation is not None:
            rr.log(
                "world/observations",
                rr.Points2D(
                    [[item.position.x_m, item.position.y_m] for item in observation.observations],
                    colors=[255, 255, 0],
                    radii=1.5,
                ),
            )
        tracking = tracking_by_time.get(timestamp_s)
        if tracking is not None:
            rr.log(
                "world/tracks",
                rr.Points2D(
                    [[item.position.x_m, item.position.y_m] for item in tracking.tracks],
                    colors=[255, 0, 255],
                    radii=2.0,
                    labels=[item.track_id for item in tracking.tracks],
                ),
            )
