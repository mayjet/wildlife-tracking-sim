from __future__ import annotations

import numpy as np


def _resample_segment(coordinates: np.ndarray, spacing_m: float) -> np.ndarray:
    lengths = np.linalg.norm(np.diff(coordinates, axis=0), axis=1)
    cumulative = np.concatenate(([0.0], np.cumsum(lengths)))
    if cumulative[-1] <= 0.0:
        raise ValueError("waypoints cannot share the same position")
    targets = np.arange(0.0, cumulative[-1], spacing_m)
    if not len(targets) or targets[-1] < cumulative[-1]:
        targets = np.append(targets, cumulative[-1])
    return np.column_stack(
        (
            np.interp(targets, cumulative, coordinates[:, 0]),
            np.interp(targets, cumulative, coordinates[:, 1]),
        )
    )


def smooth_waypoint_segments(
    points: np.ndarray,
    *,
    spacing_m: float,
    smoothing_tension: float = 0.0,
) -> tuple[np.ndarray, np.ndarray]:
    points = np.asarray(points, dtype=np.float64)
    if points.ndim != 2 or points.shape[1] != 2 or len(points) < 2:
        raise ValueError("waypoint points must have shape (n, 2), n >= 2")
    if spacing_m <= 0.0:
        raise ValueError("point_spacing_m must be positive")
    if not 0.0 <= smoothing_tension <= 1.0:
        raise ValueError("smoothing_tension must be between 0 and 1")
    if np.any(np.linalg.norm(np.diff(points, axis=0), axis=1) <= 0.0):
        raise ValueError("waypoints cannot share the same position")

    tangent_scale = 1.0 - smoothing_tension
    tangents = np.empty_like(points)
    tangents[0] = tangent_scale * (points[1] - points[0])
    tangents[-1] = tangent_scale * (points[-1] - points[-2])
    if len(points) > 2:
        tangents[1:-1] = tangent_scale * 0.5 * (points[2:] - points[:-2])

    coordinates: list[np.ndarray] = []
    segment_indices: list[int] = []
    dense_spacing = min(spacing_m / 4.0, 0.25)
    for segment_index, (start, stop) in enumerate(zip(points, points[1:])):
        chord_length = float(np.linalg.norm(stop - start))
        sample_count = max(8, int(np.ceil(chord_length / dense_spacing)) + 1)
        parameter = np.linspace(0.0, 1.0, sample_count)
        parameter2 = parameter * parameter
        parameter3 = parameter2 * parameter
        dense = (
            (2.0 * parameter3 - 3.0 * parameter2 + 1.0)[:, None] * start
            + (parameter3 - 2.0 * parameter2 + parameter)[:, None]
            * tangents[segment_index]
            + (-2.0 * parameter3 + 3.0 * parameter2)[:, None] * stop
            + (parameter3 - parameter2)[:, None] * tangents[segment_index + 1]
        )
        dense[0] = start
        dense[-1] = stop
        segment = _resample_segment(dense, spacing_m)
        segment[0] = start
        segment[-1] = stop
        if coordinates:
            segment = segment[1:]
        coordinates.extend(segment)
        segment_indices.extend([segment_index] * len(segment))
    return np.asarray(coordinates), np.asarray(segment_indices, dtype=np.int64)


def meander_smooth_segments(
    points: np.ndarray,
    *,
    spacing_m: float,
    smoothing_tension: float,
    amplitude_m: float,
    interval_m: float,
    seed: int,
) -> tuple[np.ndarray, np.ndarray]:
    if amplitude_m < 0.0 or interval_m <= 0.0:
        raise ValueError("invalid meandering route parameters")
    dense_spacing = min(spacing_m / 4.0, 0.25)
    baseline, baseline_segments = smooth_waypoint_segments(
        points,
        spacing_m=dense_spacing,
        smoothing_tension=smoothing_tension,
    )
    rng = np.random.default_rng(seed)
    coordinates: list[np.ndarray] = []
    segment_indices: list[int] = []
    for segment_index in range(len(points) - 1):
        segment = baseline[baseline_segments == segment_index].copy()
        if segment_index > 0:
            segment = np.vstack((points[segment_index], segment))
        deltas = np.diff(segment, axis=0)
        distances = np.linalg.norm(deltas, axis=1)
        cumulative = np.concatenate(([0.0], np.cumsum(distances)))
        if cumulative[-1] <= 0.0:
            raise ValueError("waypoints cannot share the same position")
        tangents = np.gradient(segment, axis=0)
        tangent_lengths = np.linalg.norm(tangents, axis=1)
        tangents = tangents / tangent_lengths[:, None]
        normals = np.column_stack((-tangents[:, 1], tangents[:, 0]))
        fraction = cumulative / cumulative[-1]
        phase = float(rng.uniform(0.0, 2.0 * np.pi))
        amplitude_scale = float(rng.uniform(0.75, 1.0))
        envelope = np.sin(np.pi * fraction)
        offset = (
            amplitude_m
            * amplitude_scale
            * envelope
            * np.sin(2.0 * np.pi * cumulative / interval_m + phase)
        )
        displaced = segment + offset[:, None] * normals
        displaced[0] = points[segment_index]
        displaced[-1] = points[segment_index + 1]
        resolved = _resample_segment(displaced, spacing_m)
        resolved[0] = points[segment_index]
        resolved[-1] = points[segment_index + 1]
        if coordinates:
            resolved = resolved[1:]
        coordinates.extend(resolved)
        segment_indices.extend([segment_index] * len(resolved))
    return np.asarray(coordinates), np.asarray(segment_indices, dtype=np.int64)
