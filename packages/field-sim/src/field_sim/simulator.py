from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from shepherd_contracts import GroundTruthFrame, GroundTruthState, Position3D, Velocity2D

from field_environment import EnvironmentCase, FeatureLayerStatus, TraversabilityValue

from .config import LinearMotion, SimulationConfig, StationaryMotion, WaypointMotion
from .herd_config import HerdSimulationConfig
from .terrain import project_to_terrain_surface


class TrajectoryValidationError(ValueError):
    pass


@dataclass(frozen=True)
class SimulationResult:
    config: SimulationConfig | HerdSimulationConfig
    frames: tuple[GroundTruthFrame, ...]

    @property
    def duration_s(self) -> float:
        return self.frames[-1].timestamp_s if self.frames else 0.0


def _motion_state(config: SimulationConfig, timestamp_s: float):
    motion = config.motion
    if isinstance(motion, StationaryMotion):
        return motion.position.x_m, motion.position.y_m, 0.0, 0.0
    if isinstance(motion, LinearMotion):
        return (
            motion.start.x_m + motion.velocity.x_mps * timestamp_s,
            motion.start.y_m + motion.velocity.y_mps * timestamp_s,
            motion.velocity.x_mps,
            motion.velocity.y_mps,
        )
    if isinstance(motion, WaypointMotion):
        timestamps = np.array([waypoint.timestamp_s for waypoint in motion.waypoints])
        positions_x = np.array([waypoint.position.x_m for waypoint in motion.waypoints])
        positions_y = np.array([waypoint.position.y_m for waypoint in motion.waypoints])
        segment = min(np.searchsorted(timestamps, timestamp_s, side="right") - 1, len(timestamps) - 2)
        segment = max(segment, 0)
        duration = timestamps[segment + 1] - timestamps[segment]
        fraction = (timestamp_s - timestamps[segment]) / duration
        x_m = positions_x[segment] + fraction * (positions_x[segment + 1] - positions_x[segment])
        y_m = positions_y[segment] + fraction * (positions_y[segment + 1] - positions_y[segment])
        return (
            float(x_m),
            float(y_m),
            float((positions_x[segment + 1] - positions_x[segment]) / duration),
            float((positions_y[segment + 1] - positions_y[segment]) / duration),
        )
    raise TypeError("unsupported motion configuration")


def _validate_position(environment_case: EnvironmentCase, x_m: float, y_m: float) -> float:
    try:
        surface_position = project_to_terrain_surface(
            environment_case.heightmap, x_m, y_m
        )
    except (IndexError, ValueError) as error:
        raise TrajectoryValidationError(str(error)) from error
    buildings = environment_case.buildings
    if (
        buildings is not None
        and buildings.status is FeatureLayerStatus.AVAILABLE
        and buildings.covers(x_m, y_m)
    ):
        raise TrajectoryValidationError("trajectory enters a building polygon")
    traversability = environment_case.traversability
    if traversability is not None:
        try:
            x_index, y_index = environment_case.heightmap.indices_at(x_m, y_m)
        except IndexError as error:
            raise TrajectoryValidationError(str(error)) from error
        if traversability.values[y_index, x_index] == TraversabilityValue.PROHIBITED:
            raise TrajectoryValidationError("trajectory enters a prohibited traversability cell")
    return surface_position.z_m


def simulate(environment_case: EnvironmentCase, config: SimulationConfig) -> SimulationResult:
    if config.case_id != environment_case.case_spec.case_id:
        raise ValueError("SimulationConfig.case_id does not match the loaded Case")
    timestamps = np.arange(round(config.duration_s / config.step_s) + 1) * config.step_s
    frames = []
    for timestamp_s in timestamps:
        x_m, y_m, velocity_x, velocity_y = _motion_state(config, float(timestamp_s))
        try:
            z_m = _validate_position(environment_case, x_m, y_m)
        except TrajectoryValidationError as error:
            raise TrajectoryValidationError(f"invalid trajectory at t={timestamp_s:g}s: {error}") from error
        state = GroundTruthState(
            timestamp_s=float(timestamp_s),
            truth_id=config.truth_id,
            position=Position3D(x_m=x_m, y_m=y_m, z_m=z_m),
            velocity=Velocity2D(x_mps=velocity_x, y_mps=velocity_y),
            age_class=config.age_class,
        )
        frames.append(GroundTruthFrame(timestamp_s=float(timestamp_s), states=(state,)))
    return SimulationResult(config=config, frames=tuple(frames))
