from __future__ import annotations

from dataclasses import dataclass
from math import atan2, cos, sin

from field_environment import EnvironmentCase
from shepherd_contracts import GroundTruthFrame

from .genesis import GenesisActorSpec, GenesisScene
from .genesis_experiment import GenesisDeerProxy, create_genesis_deer_proxy


@dataclass(frozen=True)
class GenesisDeerFrame:
    timestamp_s: float
    proxies: tuple[GenesisDeerProxy, ...]
    maximum_surface_difference_m: float


class GenesisExperimentRuntime:
    """保存済みGround TruthをGenesisの鹿Actorへ反映する表示Adapter．"""

    def __init__(self, scene: GenesisScene, truth_ids: tuple[str, ...]) -> None:
        entities_by_name = dict(zip(scene.entity_names, scene.entities))
        self.scene = scene
        self.actors = {
            truth_id: entities_by_name[f"deer-{truth_id}"] for truth_id in truth_ids
        }

    def update(self, deer_frame: GenesisDeerFrame) -> None:
        active = set()
        for proxy in deer_frame.proxies:
            active.add(proxy.truth_id)
            actor = self.actors[proxy.truth_id]
            x_m, y_m, foot_z_m = proxy.foot_position
            actor.set_pos((x_m, y_m, foot_z_m + proxy.height_m / 2.0))
            half = proxy.heading_rad / 2.0
            actor.set_quat((cos(half), 0.0, 0.0, sin(half)))
        for truth_id, actor in self.actors.items():
            if truth_id not in active:
                actor.set_pos((0.0, 0.0, -10000.0))
        self.scene.scene.step()


def genesis_deer_actor_specs(frame: GenesisDeerFrame) -> tuple[GenesisActorSpec, ...]:
    return tuple(
        GenesisActorSpec(
            name=f"deer-{proxy.truth_id}",
            position=(
                proxy.foot_position[0],
                proxy.foot_position[1],
                proxy.foot_position[2] + proxy.height_m / 2.0,
            ),
            size=(proxy.length_m, proxy.width_m, proxy.height_m),
            color=proxy.color[:3],
        )
        for proxy in frame.proxies
    )


def interpolate_genesis_deer_frames(
    first: GenesisDeerFrame,
    second: GenesisDeerFrame,
    fraction: float,
) -> GenesisDeerFrame:
    if not 0.0 <= fraction <= 1.0:
        raise ValueError("fraction must be in [0, 1]")
    first_by_id = {proxy.truth_id: proxy for proxy in first.proxies}
    proxies = []
    for end in second.proxies:
        start = first_by_id.get(end.truth_id, end)
        foot_position = tuple(
            float(start_value + (end_value - start_value) * fraction)
            for start_value, end_value in zip(start.foot_position, end.foot_position)
        )
        proxies.append(
            GenesisDeerProxy(
                truth_id=end.truth_id,
                foot_position=foot_position,
                heading_rad=float(
                    start.heading_rad + (end.heading_rad - start.heading_rad) * fraction
                ),
                height_m=end.height_m,
                length_m=end.length_m,
                width_m=end.width_m,
                color=end.color,
            )
        )
    return GenesisDeerFrame(
        timestamp_s=float(
            first.timestamp_s + (second.timestamp_s - first.timestamp_s) * fraction
        ),
        proxies=tuple(proxies),
        maximum_surface_difference_m=max(
            first.maximum_surface_difference_m,
            second.maximum_surface_difference_m,
        ),
    )


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
