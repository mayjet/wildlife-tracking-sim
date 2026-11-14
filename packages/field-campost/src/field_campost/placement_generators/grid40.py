from __future__ import annotations

from field_environment import EnvironmentCase
from shepherd_contracts import ObservationPointLayout

from ..observation_points import (
    create_observation_point_layout,
    generate_grid_observation_points,
)
from .base import PlacementDefinition


def generate(
    environment_case: EnvironmentCase,
    definition: PlacementDefinition,
) -> ObservationPointLayout:
    spacing_m = 40.0
    configured_spacing = definition.parameters.get("spacing_m", spacing_m)
    if float(configured_spacing) != spacing_m:
        raise ValueError("grid40 spacing is fixed at 40 m; use method grid for other spacing")
    placements = generate_grid_observation_points(
        environment_case,
        spacing_m=spacing_m,
        point_id_prefix=definition.method,
    )
    if not placements:
        raise ValueError("grid placement produced no valid observation points")
    profile = definition.mount.to_profile(f"{definition.layout_id}-mount")
    layout = create_observation_point_layout(
        environment_case,
        placements,
        profile,
        layout_id=definition.layout_id,
        placement_method=definition.method,
    )
    return layout.model_copy(
        update={
            "metadata": {
                **layout.metadata,
                "generator": definition.method,
                "generator_seed": definition.seed,
                "parent_layout_id": definition.parent_layout_id,
                "parameters": {"spacing_m": spacing_m},
            }
        }
    )
