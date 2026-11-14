from __future__ import annotations

import numpy as np

from field_environment import EnvironmentCase

from ..route_validation import build_route_points
from ..route_planning import plan_waypoint_route, route_coordinates_are_allowed
from ..routes import ResolvedRoute, RouteDefinition
from ..waypoints import WaypointSet
from ._smooth_path import smooth_waypoint_segments
from .base import validate_route_inputs


def generate(
    environment_case: EnvironmentCase,
    definition: RouteDefinition,
    waypoint_set: WaypointSet,
) -> ResolvedRoute:
    input_warnings = validate_route_inputs(environment_case, definition, waypoint_set)
    spacing_m = float(definition.parameters.get("point_spacing_m", 1.0))
    smoothing_tension = float(definition.parameters.get("smoothing_tension", 0.0))
    planned = plan_waypoint_route(
        environment_case,
        waypoint_set,
        parameters=definition.parameters,
    )
    selected_tension = None
    for candidate_tension in dict.fromkeys(
        (smoothing_tension, 0.25, 0.5, 0.75, 1.0)
    ):
        coordinates, control_segments = smooth_waypoint_segments(
            planned.coordinates,
            spacing_m=spacing_m,
            smoothing_tension=candidate_tension,
        )
        if route_coordinates_are_allowed(
            environment_case,
            coordinates,
            parameters=definition.parameters,
        ):
            selected_tension = candidate_tension
            break
    if selected_tension is None:
        raise ValueError("unable to smooth the planned route inside traversable space")
    segment_indices = planned.segment_indices[
        np.minimum(control_segments, len(planned.segment_indices) - 1)
    ]
    frame, warnings = build_route_points(
        environment_case,
        coordinates,
        segment_indices,
    )
    planning_warnings = []
    if planned.used_astar_segments:
        segments = ", ".join(str(index + 1) for index in planned.used_astar_segments)
        planning_warnings.append(f"A*で移動禁止領域を迂回した区間: {segments}")
    for adjustment in planned.adjustments:
        if adjustment.reason is not None:
            planning_warnings.append(
                f"{adjustment.waypoint_id}を移動可能地点へ"
                f"{adjustment.distance_m:.1f} m補正した"
            )
    if selected_tension != smoothing_tension:
        planning_warnings.append(
            f"移動禁止領域を避けるため曲線強度を"
            f"{smoothing_tension:g}から{selected_tension:g}へ調整した"
        )
    return ResolvedRoute(
        definition=definition,
        waypoint_set=waypoint_set,
        points=frame,
        warnings=tuple(
            dict.fromkeys((*input_warnings, *planning_warnings, *warnings))
        ),
        planning={
            "planner": "astar-grid",
            "used_astar_segments": [index + 1 for index in planned.used_astar_segments],
            "smoothing_tension_requested": smoothing_tension,
            "smoothing_tension_resolved": selected_tension,
            "waypoint_adjustments": [item.__dict__ for item in planned.adjustments],
        },
    )
