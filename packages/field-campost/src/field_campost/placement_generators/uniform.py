from __future__ import annotations

from field_environment import EnvironmentCase
from shepherd_contracts import ObservationPointLayout

from ..observation_points import (
    create_observation_point_layout,
    generate_grid_observation_points,
    generate_uniform_observation_points,
)
from .base import PlacementDefinition


def generate(
    environment_case: EnvironmentCase,
    definition: PlacementDefinition,
) -> ObservationPointLayout:
    configured_count = definition.parameters.get("point_count", "match_grid40")
    if configured_count == "match_grid40":
        reference_spacing_m = float(
            definition.parameters.get("reference_grid_spacing_m", 40.0)
        )
        point_count = len(
            generate_grid_observation_points(
                environment_case,
                spacing_m=reference_spacing_m,
                point_id_prefix="uniform-reference",
            )
        )
    else:
        point_count = int(configured_count)
    if point_count <= 0:
        raise ValueError("uniform placement requires a positive resolved point count")
    placements = generate_uniform_observation_points(
        environment_case,
        point_count=point_count,
        point_id_prefix=definition.method,
    )
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
                "parameters": {
                    **definition.parameters,
                    "resolved_point_count": point_count,
                },
            }
        }
    )
