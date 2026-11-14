from __future__ import annotations

from pathlib import Path

from field_environment import EnvironmentCase

from ..routes import ResolvedRoute, RouteDefinition, load_route_definition
from ..waypoints import WaypointSet, load_waypoint_set, validate_waypoint_set


def load_route_inputs(
    route_path: str | Path,
    *,
    start: str | Path | None = None,
) -> tuple[RouteDefinition, WaypointSet, Path]:
    definition, resolved_route_path = load_route_definition(route_path, start=start)
    waypoint_path = (resolved_route_path.parent / definition.waypoint_set).resolve()
    waypoint_set, _ = load_waypoint_set(waypoint_path)
    return definition, waypoint_set, resolved_route_path


def validate_route_inputs(
    environment_case: EnvironmentCase,
    definition: RouteDefinition,
    waypoint_set: WaypointSet,
) -> tuple[str, ...]:
    if definition.route_group_id != waypoint_set.waypoint_set_id:
        raise ValueError("route_group_id must equal waypoint_set_id")
    if bool(definition.parameters.get("snap_waypoints", True)):
        if waypoint_set.case_id != environment_case.case_spec.case_id:
            raise ValueError("WaypointSet.case_id does not match the loaded Case")
        warnings = []
        for waypoint in waypoint_set.waypoints:
            try:
                environment_case.heightmap.surface_elevation_at(
                    waypoint.x_m, waypoint.y_m
                )
            except IndexError as error:
                raise ValueError(
                    f"waypoint {waypoint.waypoint_id} is outside the terrain surface"
                ) from error
            from shapely.geometry import Point

            if not environment_case.farm_boundary.polygon.covers(
                Point(waypoint.x_m, waypoint.y_m)
            ):
                warnings.append(f"{waypoint.waypoint_id}: outside farm boundary")
            if environment_case.forest is not None and environment_case.forest.covers(
                waypoint.x_m, waypoint.y_m
            ):
                warnings.append(f"{waypoint.waypoint_id}: inside forest")
        return tuple(warnings)
    return validate_waypoint_set(environment_case, waypoint_set)
