from __future__ import annotations

from pydantic import Field, model_validator

from ._base import ContractModel
from .animals import AgeClass
from .coordinates import Position2D


class Observation(ContractModel):
    timestamp_s: float = Field(ge=0.0)
    camera_id: str = Field(min_length=1)
    observation_id: str = Field(min_length=1)
    position: Position2D
    age_class: AgeClass = AgeClass.UNKNOWN


class ObservationFrame(ContractModel):
    timestamp_s: float = Field(ge=0.0)
    observations: tuple[Observation, ...] = ()

    @model_validator(mode="after")
    def validate_timestamps_and_ids(self) -> "ObservationFrame":
        if any(observation.timestamp_s != self.timestamp_s for observation in self.observations):
            raise ValueError("all observations must match the frame timestamp")
        observation_ids = [observation.observation_id for observation in self.observations]
        if len(observation_ids) != len(set(observation_ids)):
            raise ValueError("observation_id values must be unique within a frame")
        return self
