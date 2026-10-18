from __future__ import annotations

from enum import Enum
from pathlib import PurePosixPath

from pydantic import Field, field_validator, model_validator

from ._base import ContractModel, JsonValue


def _validate_case_relative_reference(value: str) -> str:
    path = PurePosixPath(value)
    if not value or path.is_absolute() or ".." in path.parts:
        raise ValueError("artifact references must be relative to the case directory")
    return value


class AlgorithmSpec(ContractModel):
    name: str = Field(min_length=1)
    version: str = Field(min_length=1)
    parameters: dict[str, JsonValue] = Field(default_factory=dict)


class DatasetManifest(ContractModel):
    schema_version: str = Field(min_length=1)
    case_id: str = Field(min_length=1)
    dataset_id: str = Field(min_length=1)
    seed: int
    duration_s: float = Field(gt=0.0)
    simulation_step_s: float = Field(gt=0.0)
    scenario_config: dict[str, JsonValue] = Field(default_factory=dict)
    observation_data_ref: str
    ground_truth_data_ref: str

    @field_validator("observation_data_ref", "ground_truth_data_ref")
    @classmethod
    def validate_references(cls, value: str) -> str:
        return _validate_case_relative_reference(value)

    @model_validator(mode="after")
    def validate_dataset(self) -> "DatasetManifest":
        if self.simulation_step_s > self.duration_s:
            raise ValueError("simulation_step_s cannot exceed duration_s")
        if self.observation_data_ref == self.ground_truth_data_ref:
            raise ValueError("observation and ground-truth data references must be separate")
        return self


class RunStatus(str, Enum):
    CREATED = "CREATED"
    RUNNING = "RUNNING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"


class RunManifest(ContractModel):
    schema_version: str = Field(min_length=1)
    case_id: str = Field(min_length=1)
    dataset_id: str = Field(min_length=1)
    run_id: str = Field(min_length=1)
    seed: int
    algorithm: AlgorithmSpec
    input_data_refs: tuple[str, ...] = Field(min_length=1)
    artifact_refs: tuple[str, ...] = ()
    environment: dict[str, JsonValue] = Field(default_factory=dict)
    status: RunStatus = RunStatus.CREATED

    @field_validator("input_data_refs", "artifact_refs")
    @classmethod
    def validate_references(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        return tuple(_validate_case_relative_reference(value) for value in values)
