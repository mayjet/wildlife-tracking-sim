from __future__ import annotations

import numpy as np

from field_environment import EnvironmentCase

from ..route_validation import build_route_points
from ..routes import ResolvedRoute, RouteDefinition
from ..waypoints import WaypointSet
from .base import validate_route_inputs


def generate(
    environment_case: EnvironmentCase,
    definition: RouteDefinition,
    waypoint_set: WaypointSet,
) -> ResolvedRoute:
    input_warnings = validate_route_inputs(environment_case, definition, waypoint_set)
    spacing_m = float(definition.parameters.get("point_spacing_m", 1.0))
    if spacing_m <= 0.0:
        raise ValueError("point_spacing_m must be positive")
    coordinates = []
    segment_indices = []
    points = np.asarray([(point.x_m, point.y_m) for point in waypoint_set.waypoints])
    for segment_index, (start, stop) in enumerate(zip(points, points[1:])):
        length = float(np.linalg.norm(stop - start))
        sample_count = max(2, int(np.ceil(length / spacing_m)) + 1)
        segment = np.linspace(start, stop, sample_count)
        if coordinates:
            segment = segment[1:]
        coordinates.extend(segment)
        segment_indices.extend([segment_index] * len(segment))
    frame, warnings = build_route_points(
        environment_case,
        np.asarray(coordinates),
        np.asarray(segment_indices),
    )
    return ResolvedRoute(
        definition=definition,
        waypoint_set=waypoint_set,
        points=frame,
        warnings=tuple(dict.fromkeys((*input_warnings, *warnings))),
    )
