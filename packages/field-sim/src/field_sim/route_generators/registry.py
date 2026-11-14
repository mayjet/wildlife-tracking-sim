from __future__ import annotations

from importlib import import_module
from typing import Callable

from field_environment import EnvironmentCase

from ..routes import ResolvedRoute, RouteDefinition
from ..waypoints import WaypointSet

RouteGenerator = Callable[[EnvironmentCase, RouteDefinition, WaypointSet], ResolvedRoute]

_BUILTIN_MODULES = {
    "direct": "field_sim.route_generators.direct",
    "smooth": "field_sim.route_generators.smooth",
    "meandering": "field_sim.route_generators.meandering",
}


def available_route_methods() -> tuple[str, ...]:
    return tuple(sorted(_BUILTIN_MODULES))


def resolve_route_generator(definition: RouteDefinition) -> RouteGenerator:
    module_name = definition.module or _BUILTIN_MODULES.get(definition.method)
    if module_name is None:
        raise ValueError(
            f"unknown route method {definition.method!r}; custom methods must declare module"
        )
    module = import_module(module_name)
    generator = getattr(module, "generate", None)
    if not callable(generator):
        raise TypeError(f"route module {module_name!r} must define callable generate")
    return generator


def generate_resolved_route(
    environment_case: EnvironmentCase,
    definition: RouteDefinition,
    waypoint_set: WaypointSet,
) -> ResolvedRoute:
    route = resolve_route_generator(definition)(environment_case, definition, waypoint_set)
    if route.definition.route_id != definition.route_id:
        raise ValueError("route generator returned a different route_id")
    return route
