from __future__ import annotations

import numpy as np
from shepherd_contracts import GroundTruthFrame, GroundTruthState, Position3D, Velocity2D

from field_environment import EnvironmentCase

from .herd_avoidance import resolve_herd_position
from .herd_config import HerdSimulationConfig
from .herd_formation import HerdMember, create_herd_members
from .routes import ResolvedRoute
from .simulator import SimulationResult, _validate_position


def _route_position(route: ResolvedRoute, distance_m: float) -> tuple[np.ndarray, np.ndarray]:
    distances = route.points["distance_m"].to_numpy(dtype=float)
    x_values = route.points["x_m"].to_numpy(dtype=float)
    y_values = route.points["y_m"].to_numpy(dtype=float)
    clipped = float(np.clip(distance_m, 0.0, distances[-1]))
    x_m = float(np.interp(clipped, distances, x_values))
    y_m = float(np.interp(clipped, distances, y_values))
    probe = min(max(route.length_m / max(len(distances), 2), 0.5), 2.0)
    before = max(0.0, clipped - probe)
    after = min(route.length_m, clipped + probe)
    tangent = np.asarray(
        (
            np.interp(after, distances, x_values) - np.interp(before, distances, x_values),
            np.interp(after, distances, y_values) - np.interp(before, distances, y_values),
        ),
        dtype=np.float64,
    )
    norm = float(np.linalg.norm(tangent))
    if norm <= 1.0e-9:
        tangent = np.asarray((1.0, 0.0))
    else:
        tangent /= norm
    return np.asarray((x_m, y_m)), tangent


def _desired_position(
    route: ResolvedRoute,
    member: HerdMember,
    timestamp_s: float,
    config: HerdSimulationConfig,
) -> tuple[np.ndarray, np.ndarray]:
    delay_distance = config.speed_mps * config.profile.follower_delay_s
    speed_drift_m = float(
        np.clip(
            member.speed_offset_mps * timestamp_s,
            -config.profile.group_radius_m / 2.0,
            config.profile.group_radius_m / 2.0,
        )
    )
    longitudinal_m = (
        member.longitudinal_offset_m
        + speed_drift_m
        - (0.0 if member.is_leader else delay_distance)
    )
    lateral_m = member.lateral_offset_m
    offset_norm_m = float(np.hypot(longitudinal_m, lateral_m))
    if offset_norm_m > config.profile.group_radius_m:
        scale = config.profile.group_radius_m / offset_norm_m
        longitudinal_m *= scale
        lateral_m *= scale
    center, tangent = _route_position(route, config.speed_mps * timestamp_s)
    normal = np.asarray((-tangent[1], tangent[0]))
    return center + tangent * longitudinal_m + normal * lateral_m, tangent


# 確定ルートへ追従する複数個体の群れ真値を生成する．
def simulate_herd(
    environment_case: EnvironmentCase,
    resolved_route: ResolvedRoute,
    herd_config: HerdSimulationConfig,
) -> SimulationResult:
    if herd_config.case_id != environment_case.case_spec.case_id:
        raise ValueError("HerdSimulationConfig.case_id does not match the loaded Case")
    if herd_config.route_id != resolved_route.definition.route_id:
        raise ValueError("HerdSimulationConfig.route_id does not match ResolvedRoute")
    members = create_herd_members(
        herd_config.herd_id, herd_config.profile, herd_config.seed
    )
    duration_s = resolved_route.length_m / herd_config.speed_mps
    step_count = int(np.ceil(duration_s / herd_config.step_s))
    timestamps = np.arange(step_count + 1, dtype=float) * herd_config.step_s
    previous_positions: dict[str, np.ndarray] = {}
    frames = []
    for timestamp_s in timestamps:
        leader_center, _ = _route_position(
            resolved_route,
            min(resolved_route.length_m, herd_config.speed_mps * timestamp_s),
        )
        occupied: list[np.ndarray] = []
        states = []
        for member in members:
            desired, tangent = _desired_position(
                resolved_route, member, float(timestamp_s), herd_config
            )
            previous = previous_positions.get(member.truth_id, desired)
            position = resolve_herd_position(
                environment_case,
                desired,
                previous,
                leader_center,
                tuple(occupied),
                minimum_separation_m=herd_config.profile.minimum_separation_m,
                candidate_angles_deg=herd_config.local_avoidance_angles_deg,
                candidate_radius_m=herd_config.local_avoidance_radius_m,
                astar_lookahead_m=herd_config.astar_lookahead_m,
            )
            z_m = _validate_position(
                environment_case, float(position[0]), float(position[1])
            )
            velocity_xy = (
                (position - previous) / herd_config.step_s
                if timestamp_s > 0.0
                else tangent * (herd_config.speed_mps + member.speed_offset_mps)
            )
            states.append(
                GroundTruthState(
                    timestamp_s=float(timestamp_s),
                    truth_id=member.truth_id,
                    group_truth_id=herd_config.herd_id,
                    is_group_leader=member.is_leader,
                    position=Position3D(
                        x_m=float(position[0]), y_m=float(position[1]), z_m=float(z_m)
                    ),
                    velocity=Velocity2D(
                        x_mps=float(velocity_xy[0]), y_mps=float(velocity_xy[1])
                    ),
                    age_class=member.age_class,
                )
            )
            occupied.append(position)
            previous_positions[member.truth_id] = position
        frames.append(
            GroundTruthFrame(timestamp_s=float(timestamp_s), states=tuple(states))
        )
    return SimulationResult(config=herd_config, frames=tuple(frames))
