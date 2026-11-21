from __future__ import annotations

from dataclasses import dataclass
from math import atan2

from field_environment import EnvironmentCase
from shepherd_contracts import GroundTruthFrame

from .genesis_experiment import GenesisDeerProxy, create_genesis_deer_proxy


@dataclass(frozen=True)
class GenesisDeerFrame:
    timestamp_s: float
    proxies: tuple[GenesisDeerProxy, ...]
    maximum_surface_difference_m: float


# Ground TruthのXYを変えず，Genesis用の不透明な鹿代理物体を地表へ強制追従させる．
def build_genesis_deer_frame(
    environment_case: EnvironmentCase,
    frame: GroundTruthFrame,
    *,
    foot_clearance_m: float = 0.03,
) -> GenesisDeerFrame:
    proxies = []
    surface_differences = []
    for state in frame.states:
        ground_z_m = environment_case.heightmap.surface_elevation_at(
            state.position.x_m, state.position.y_m
        )
        source_z_m = getattr(state.position, "z_m", None)
        if source_z_m is not None:
            surface_differences.append(abs(float(source_z_m) - ground_z_m))
        heading_rad = 0.0
        if state.velocity is not None and (
            state.velocity.x_mps != 0.0 or state.velocity.y_mps != 0.0
        ):
            heading_rad = atan2(state.velocity.y_mps, state.velocity.x_mps)
        proxies.append(
            create_genesis_deer_proxy(
                environment_case,
                truth_id=state.truth_id,
                x_m=state.position.x_m,
                y_m=state.position.y_m,
                heading_rad=heading_rad,
                foot_clearance_m=foot_clearance_m,
            )
        )
    return GenesisDeerFrame(
        timestamp_s=frame.timestamp_s,
        proxies=tuple(proxies),
        maximum_surface_difference_m=max(surface_differences, default=0.0),
    )
