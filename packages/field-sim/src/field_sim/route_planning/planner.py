from __future__ import annotations

from dataclasses import dataclass
from heapq import heappop, heappush
from math import ceil, hypot, sqrt
from typing import Mapping

import numpy as np

from field_environment import EnvironmentCase, TraversabilityValue

from ..waypoints import WaypointSet


@dataclass(frozen=True)
class WaypointAdjustment:
    waypoint_id: str
    requested_x_m: float
    requested_y_m: float
    resolved_x_m: float
    resolved_y_m: float
    distance_m: float
    reason: str | None


@dataclass(frozen=True)
class PlannedWaypointRoute:
    coordinates: np.ndarray
    segment_indices: np.ndarray
    adjustments: tuple[WaypointAdjustment, ...]
    used_astar_segments: tuple[int, ...]


def _settings(parameters: Mapping[str, object]) -> dict[str, float | bool]:
    return {
        "auto_avoid_prohibited": bool(parameters.get("auto_avoid_prohibited", True)),
        "snap_waypoints": bool(parameters.get("snap_waypoints", True)),
        "snap_radius_m": float(parameters.get("snap_radius_m", 30.0)),
        "obstacle_clearance_m": float(parameters.get("obstacle_clearance_m", 2.0)),
        "difficult_cost_multiplier": float(
            parameters.get("difficult_cost_multiplier", 4.0)
        ),
        "unknown_cost_multiplier": float(parameters.get("unknown_cost_multiplier", 1.0)),
    }


def _dilate(mask: np.ndarray, radius_cells: int) -> np.ndarray:
    if radius_cells <= 0:
        return mask.copy()
    height, width = mask.shape
    result = mask.copy()
    for y_offset in range(-radius_cells, radius_cells + 1):
        for x_offset in range(-radius_cells, radius_cells + 1):
            if x_offset * x_offset + y_offset * y_offset > radius_cells * radius_cells:
                continue
            source_y_start = max(0, -y_offset)
            source_y_stop = min(height, height - y_offset)
            source_x_start = max(0, -x_offset)
            source_x_stop = min(width, width - x_offset)
            target_y_start = source_y_start + y_offset
            target_y_stop = source_y_stop + y_offset
            target_x_start = source_x_start + x_offset
            target_x_stop = source_x_stop + x_offset
            result[target_y_start:target_y_stop, target_x_start:target_x_stop] |= mask[
                source_y_start:source_y_stop,
                source_x_start:source_x_stop,
            ]
    return result


def _cost_grid(
    environment_case: EnvironmentCase,
    parameters: Mapping[str, object],
) -> tuple[np.ndarray, np.ndarray]:
    settings = _settings(parameters)
    shape = environment_case.heightmap.values.shape
    values = (
        np.zeros(shape, dtype=np.uint8)
        if environment_case.traversability is None
        else environment_case.traversability.values
    )
    prohibited = values == TraversabilityValue.PROHIBITED
    clearance_m = float(settings["obstacle_clearance_m"])
    radius_cells = int(ceil(clearance_m / environment_case.heightmap.grid.cell_size_m))
    blocked = _dilate(prohibited, radius_cells)
    costs = np.ones(shape, dtype=np.float64)
    costs[values == TraversabilityValue.UNKNOWN] = float(
        settings["unknown_cost_multiplier"]
    )
    costs[values == TraversabilityValue.DIFFICULT] = float(
        settings["difficult_cost_multiplier"]
    )
    costs[blocked] = np.inf
    return costs, blocked


def resolve_waypoint_position(
    environment_case: EnvironmentCase,
    x_m: float,
    y_m: float,
    *,
    parameters: Mapping[str, object] | None = None,
    waypoint_id: str = "waypoint",
) -> WaypointAdjustment:
    parameters = parameters or {}
    settings = _settings(parameters)
    costs, blocked = _cost_grid(environment_case, parameters)
    try:
        x_index, y_index = environment_case.heightmap.indices_at(x_m, y_m)
    except IndexError as error:
        raise ValueError(f"{waypoint_id} is outside the terrain surface") from error
    if not blocked[y_index, x_index]:
        return WaypointAdjustment(
            waypoint_id, x_m, y_m, x_m, y_m, 0.0, None
        )
    if not bool(settings["snap_waypoints"]):
        raise ValueError(f"{waypoint_id} is inside prohibited traversability")
    radius_cells = int(
        ceil(float(settings["snap_radius_m"]) / environment_case.heightmap.grid.cell_size_m)
    )
    best: tuple[float, int, int] | None = None
    for candidate_y in range(max(0, y_index - radius_cells), min(costs.shape[0], y_index + radius_cells + 1)):
        for candidate_x in range(max(0, x_index - radius_cells), min(costs.shape[1], x_index + radius_cells + 1)):
            if not np.isfinite(costs[candidate_y, candidate_x]):
                continue
            center = environment_case.heightmap.cell_center(candidate_x, candidate_y)
            distance = hypot(center.x_m - x_m, center.y_m - y_m)
            if distance <= float(settings["snap_radius_m"]) and (
                best is None or distance < best[0]
            ):
                best = (distance, candidate_x, candidate_y)
    if best is None:
        raise ValueError(
            f"no traversable cell exists within {float(settings['snap_radius_m']):g} m of {waypoint_id}"
        )
    distance, candidate_x, candidate_y = best
    center = environment_case.heightmap.cell_center(candidate_x, candidate_y)
    return WaypointAdjustment(
        waypoint_id,
        x_m,
        y_m,
        center.x_m,
        center.y_m,
        distance,
        "snapped from prohibited traversability",
    )


def _segment_is_allowed(
    environment_case: EnvironmentCase,
    blocked: np.ndarray,
    start: np.ndarray,
    stop: np.ndarray,
) -> bool:
    length = float(np.linalg.norm(stop - start))
    spacing = max(0.5, environment_case.heightmap.grid.cell_size_m / 4.0)
    sample_count = max(2, int(ceil(length / spacing)) + 1)
    for x_m, y_m in np.linspace(start, stop, sample_count):
        try:
            x_index, y_index = environment_case.heightmap.indices_at(float(x_m), float(y_m))
        except IndexError:
            return False
        if blocked[y_index, x_index]:
            return False
    return True


def route_coordinates_are_allowed(
    environment_case: EnvironmentCase,
    coordinates: np.ndarray,
    *,
    parameters: Mapping[str, object] | None = None,
) -> bool:
    _, blocked = _cost_grid(environment_case, parameters or {})
    return all(
        _segment_is_allowed(environment_case, blocked, start, stop)
        for start, stop in zip(coordinates, coordinates[1:])
    )


def _astar(
    costs: np.ndarray,
    start: tuple[int, int],
    goal: tuple[int, int],
) -> list[tuple[int, int]]:
    if not np.isfinite(costs[start[1], start[0]]) or not np.isfinite(costs[goal[1], goal[0]]):
        raise ValueError("A* start or goal is prohibited")
    height, width = costs.shape
    frontier: list[tuple[float, float, tuple[int, int]]] = [(0.0, 0.0, start)]
    came_from: dict[tuple[int, int], tuple[int, int] | None] = {start: None}
    best_cost = {start: 0.0}
    neighbors = (
        (-1, 0, 1.0),
        (1, 0, 1.0),
        (0, -1, 1.0),
        (0, 1, 1.0),
        (-1, -1, sqrt(2.0)),
        (-1, 1, sqrt(2.0)),
        (1, -1, sqrt(2.0)),
        (1, 1, sqrt(2.0)),
    )
    while frontier:
        _, current_cost, current = heappop(frontier)
        if current == goal:
            break
        if current_cost > best_cost[current]:
            continue
        for x_offset, y_offset, step_length in neighbors:
            next_x, next_y = current[0] + x_offset, current[1] + y_offset
            if not (0 <= next_x < width and 0 <= next_y < height):
                continue
            if not np.isfinite(costs[next_y, next_x]):
                continue
            if x_offset and y_offset:
                if not np.isfinite(costs[current[1], next_x]) or not np.isfinite(
                    costs[next_y, current[0]]
                ):
                    continue
            next_cost = current_cost + step_length * float(costs[next_y, next_x])
            next_node = (next_x, next_y)
            if next_cost >= best_cost.get(next_node, np.inf):
                continue
            best_cost[next_node] = next_cost
            came_from[next_node] = current
            heuristic = hypot(goal[0] - next_x, goal[1] - next_y)
            heappush(frontier, (next_cost + heuristic, next_cost, next_node))
    if goal not in came_from:
        raise ValueError("no traversable route exists between consecutive waypoints")
    path = []
    node: tuple[int, int] | None = goal
    while node is not None:
        path.append(node)
        node = came_from[node]
    return list(reversed(path))


def _astar_near_segment(
    costs: np.ndarray,
    start: tuple[int, int],
    goal: tuple[int, int],
) -> list[tuple[int, int]]:
    height, width = costs.shape
    maximum_margin = max(width, height)
    margins = tuple(dict.fromkeys((10, 25, 50, 100, 200, maximum_margin)))
    last_error: ValueError | None = None
    for margin in margins:
        min_x = max(0, min(start[0], goal[0]) - margin)
        max_x = min(width, max(start[0], goal[0]) + margin + 1)
        min_y = max(0, min(start[1], goal[1]) - margin)
        max_y = min(height, max(start[1], goal[1]) + margin + 1)
        local_start = (start[0] - min_x, start[1] - min_y)
        local_goal = (goal[0] - min_x, goal[1] - min_y)
        try:
            local_path = _astar(
                costs[min_y:max_y, min_x:max_x],
                local_start,
                local_goal,
            )
            return [(x_index + min_x, y_index + min_y) for x_index, y_index in local_path]
        except ValueError as error:
            last_error = error
    raise ValueError("no traversable route exists between consecutive waypoints") from last_error


def _simplify(
    environment_case: EnvironmentCase,
    blocked: np.ndarray,
    coordinates: np.ndarray,
) -> np.ndarray:
    selected = [coordinates[0]]
    start_index = 0
    while start_index < len(coordinates) - 1:
        stop_index = len(coordinates) - 1
        while stop_index > start_index + 1:
            if _segment_is_allowed(
                environment_case,
                blocked,
                coordinates[start_index],
                coordinates[stop_index],
            ):
                break
            stop_index -= 1
        selected.append(coordinates[stop_index])
        start_index = stop_index
    return np.asarray(selected)


def plan_waypoint_route(
    environment_case: EnvironmentCase,
    waypoint_set: WaypointSet,
    *,
    parameters: Mapping[str, object] | None = None,
) -> PlannedWaypointRoute:
    parameters = parameters or {}
    settings = _settings(parameters)
    costs, blocked = _cost_grid(environment_case, parameters)
    adjustments = tuple(
        resolve_waypoint_position(
            environment_case,
            waypoint.x_m,
            waypoint.y_m,
            parameters=parameters,
            waypoint_id=waypoint.waypoint_id,
        )
        for waypoint in waypoint_set.waypoints
    )
    resolved = np.asarray(
        [(item.resolved_x_m, item.resolved_y_m) for item in adjustments],
        dtype=np.float64,
    )
    coordinates: list[np.ndarray] = []
    segment_indices: list[int] = []
    used_astar = []
    for segment_index, (start, stop) in enumerate(zip(resolved, resolved[1:])):
        if _segment_is_allowed(environment_case, blocked, start, stop):
            segment = np.vstack((start, stop))
        elif bool(settings["auto_avoid_prohibited"]):
            start_indices = environment_case.heightmap.indices_at(*start)
            stop_indices = environment_case.heightmap.indices_at(*stop)
            nodes = _astar_near_segment(costs, start_indices, stop_indices)
            centers = np.asarray(
                [
                    (
                        environment_case.heightmap.cell_center(x_index, y_index).x_m,
                        environment_case.heightmap.cell_center(x_index, y_index).y_m,
                    )
                    for x_index, y_index in nodes
                ]
            )
            centers[0] = start
            centers[-1] = stop
            segment = _simplify(environment_case, blocked, centers)
            used_astar.append(segment_index)
        else:
            raise ValueError(
                f"waypoint segment {segment_index + 1} crosses prohibited traversability"
            )
        if coordinates:
            segment = segment[1:]
        coordinates.extend(segment)
        segment_indices.extend([segment_index] * len(segment))
    return PlannedWaypointRoute(
        coordinates=np.asarray(coordinates),
        segment_indices=np.asarray(segment_indices, dtype=np.int64),
        adjustments=adjustments,
        used_astar_segments=tuple(used_astar),
    )
