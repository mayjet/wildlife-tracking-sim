from __future__ import annotations

from math import cos, radians, sin

import numpy as np

from field_environment import EnvironmentCase

from .route_planning.planner import plan_waypoint_route, resolve_waypoint_position
from .simulator import TrajectoryValidationError, _validate_position
from .waypoints import WaypointSet, WaypointSpec


def _is_separated(
    candidate: np.ndarray,
    occupied: tuple[np.ndarray, ...],
    minimum_separation_m: float,
) -> bool:
    return all(
        float(np.linalg.norm(candidate - position)) >= minimum_separation_m
        for position in occupied
    )


def _valid_candidate(
    environment_case: EnvironmentCase,
    candidate: np.ndarray,
    occupied: tuple[np.ndarray, ...],
    minimum_separation_m: float,
) -> bool:
    try:
        _validate_position(environment_case, float(candidate[0]), float(candidate[1]))
    except TrajectoryValidationError:
        return False
    return _is_separated(candidate, occupied, minimum_separation_m)


# 希望位置が障害物内の場合に局所旋回と既存グリッド補正で回避する．
def resolve_herd_position(
    environment_case: EnvironmentCase,
    desired: np.ndarray,
    previous: np.ndarray,
    herd_center: np.ndarray,
    occupied: tuple[np.ndarray, ...],
    *,
    minimum_separation_m: float,
    candidate_angles_deg: tuple[float, ...],
    candidate_radius_m: float,
    astar_lookahead_m: float,
) -> np.ndarray:
    desired = np.asarray(desired, dtype=np.float64)
    previous = np.asarray(previous, dtype=np.float64)
    if _valid_candidate(
        environment_case, desired, occupied, minimum_separation_m
    ):
        return desired

    direction = desired - previous
    norm = float(np.linalg.norm(direction))
    if norm <= 1.0e-9:
        direction = herd_center - previous
        norm = float(np.linalg.norm(direction))
    unit = direction / norm if norm > 1.0e-9 else np.asarray((1.0, 0.0))
    step = max(norm, candidate_radius_m)
    candidates: list[tuple[float, np.ndarray]] = []
    for angle_deg in candidate_angles_deg:
        angle = radians(angle_deg)
        rotated = np.asarray(
            (
                unit[0] * cos(angle) - unit[1] * sin(angle),
                unit[0] * sin(angle) + unit[1] * cos(angle),
            )
        )
        candidate = previous + rotated * step
        if _valid_candidate(
            environment_case, candidate, occupied, minimum_separation_m
        ):
            score = float(np.linalg.norm(candidate - desired)) + 0.1 * float(
                np.linalg.norm(candidate - herd_center)
            )
            candidates.append((score, candidate))
    if candidates:
        return min(candidates, key=lambda item: item[0])[1]

    adjustment = resolve_waypoint_position(
        environment_case,
        float(desired[0]),
        float(desired[1]),
        parameters={
            "snap_waypoints": True,
            "snap_radius_m": max(astar_lookahead_m, candidate_radius_m),
            "obstacle_clearance_m": minimum_separation_m / 2.0,
        },
        waypoint_id="herd-member",
    )
    snapped = np.asarray((adjustment.resolved_x_m, adjustment.resolved_y_m))
    try:
        planned = plan_waypoint_route(
            environment_case,
            WaypointSet(
                waypoint_set_id="herd-local-detour",
                case_id=environment_case.case_spec.case_id,
                waypoints=(
                    WaypointSpec(
                        id="current",
                        x_m=float(previous[0]),
                        y_m=float(previous[1]),
                    ),
                    WaypointSpec(
                        id="target",
                        x_m=float(snapped[0]),
                        y_m=float(snapped[1]),
                    ),
                ),
            ),
            parameters={
                "auto_avoid_prohibited": True,
                "snap_waypoints": True,
                "snap_radius_m": max(astar_lookahead_m, candidate_radius_m),
                "obstacle_clearance_m": minimum_separation_m / 2.0,
            },
        )
        remaining_m = candidate_radius_m
        candidate = planned.coordinates[0].copy()
        for start, stop in zip(planned.coordinates, planned.coordinates[1:]):
            segment = stop - start
            length_m = float(np.linalg.norm(segment))
            if length_m <= remaining_m:
                candidate = stop.copy()
                remaining_m -= length_m
                continue
            candidate = start + segment * (remaining_m / length_m)
            break
        if _valid_candidate(
            environment_case, candidate, occupied, minimum_separation_m
        ):
            return candidate
    except ValueError:
        pass

    for radius in np.arange(
        minimum_separation_m,
        candidate_radius_m * 4.0 + minimum_separation_m,
        minimum_separation_m,
    ):
        for angle in np.linspace(0.0, 2.0 * np.pi, 24, endpoint=False):
            candidate = herd_center + radius * np.asarray((cos(angle), sin(angle)))
            if _valid_candidate(
                environment_case, candidate, occupied, minimum_separation_m
            ):
                return candidate
    raise TrajectoryValidationError("no collision-free herd position is available")
