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
    grpc_url: str | None = None,
    spawn: bool = False,
) -> None:
    if recording_path is None:
        raise ValueError("recording_path is required for reproducible replay")
    from .live_session import RerunLiveSession

    session = RerunLiveSession(
        run_id=application_id,
        recording_path=recording_path,
        grpc_url=grpc_url,
        application_id=application_id,
    )
    session.log_environment(environment_case, observation_point_layout)
    observations_by_time = {frame.timestamp_s: frame for frame in observation_frames}
    tracking_by_time = {frame.timestamp_s: frame for frame in tracking_frames}
    truth_by_time = {frame.timestamp_s: frame for frame in ground_truth_frames}
    timestamps = sorted(
        set(observations_by_time) | set(tracking_by_time) | set(truth_by_time)
    )
    for timestamp_s in timestamps:
        session.log_frame(
            timestamp_s=timestamp_s,
            ground_truth=truth_by_time.get(timestamp_s),
            observations=observations_by_time.get(timestamp_s),
            tracking=tracking_by_time.get(timestamp_s),
        )
    session.close()
