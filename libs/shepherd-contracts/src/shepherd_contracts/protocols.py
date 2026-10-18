from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Protocol, runtime_checkable

from pydantic import Field

from ._base import ContractModel, JsonValue
from .coordinates import AxisAlignedBounds2D, Position2D
from .environment import CameraLayout, CaseSpec
from .ground_truth import GroundTruthState
from .observations import Observation
from .tracking import TrackingFrame


class PlacementEnvironment(ContractModel):
    case: CaseSpec
    candidate_positions: tuple[Position2D, ...] = ()


class PlacementConstraints(ContractModel):
    maximum_camera_count: int = Field(gt=0)
    allowed_region: AxisAlignedBounds2D | None = None
    minimum_camera_separation_m: float = Field(ge=0.0, default=0.0)


class LocalEnvironmentView(ContractModel):
    center: Position2D
    radius_m: float = Field(gt=0.0)
    traversable_bounds: AxisAlignedBounds2D | None = None
    attributes: dict[str, JsonValue] = Field(default_factory=dict)


@runtime_checkable
class Tracker(Protocol):
    def reset(self, config: Mapping[str, JsonValue], seed: int) -> None: ...

    def step(
        self, timestamp_s: float, observations: Sequence[Observation]
    ) -> TrackingFrame: ...

    def finalize(self) -> TrackingFrame | None: ...


@runtime_checkable
class CameraPlacementMethod(Protocol):
    def generate(
        self,
        environment: PlacementEnvironment,
        constraints: PlacementConstraints,
        seed: int,
    ) -> CameraLayout: ...


@runtime_checkable
class DeerBehaviorModel(Protocol):
    def reset(self, config: Mapping[str, JsonValue], seed: int) -> None: ...

    def step(
        self,
        timestamp_s: float,
        step_s: float,
        deer_states: Sequence[GroundTruthState],
        local_environment: LocalEnvironmentView,
    ) -> Sequence[GroundTruthState]: ...

