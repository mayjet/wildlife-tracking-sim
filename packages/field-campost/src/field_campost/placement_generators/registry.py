from __future__ import annotations

from importlib import import_module
from typing import Callable

from field_environment import EnvironmentCase
from shepherd_contracts import ObservationPointLayout

from .base import PlacementDefinition

PlacementGenerator = Callable[[EnvironmentCase, PlacementDefinition], ObservationPointLayout]

_BUILTIN_MODULES = {
    "grid": "field_campost.placement_generators.grid",
    "grid40": "field_campost.placement_generators.grid40",
    "uniform": "field_campost.placement_generators.uniform",
}


def available_placement_methods() -> tuple[str, ...]:
    return tuple(sorted(_BUILTIN_MODULES))


def resolve_placement_generator(definition: PlacementDefinition) -> PlacementGenerator:
    module_name = definition.module or _BUILTIN_MODULES.get(definition.method)
    if module_name is None:
        raise ValueError(
            f"unknown placement method {definition.method!r}; "
            "custom methods must declare module"
        )
    module = import_module(module_name)
    generator = getattr(module, "generate", None)
    if not callable(generator):
        raise TypeError(f"placement module {module_name!r} must define callable generate")
    return generator


def generate_placement_layout(
    environment_case: EnvironmentCase,
    definition: PlacementDefinition,
) -> ObservationPointLayout:
    layout = resolve_placement_generator(definition)(environment_case, definition)
    if layout.layout_id != definition.layout_id:
        raise ValueError("placement generator returned a different layout_id")
    return layout
