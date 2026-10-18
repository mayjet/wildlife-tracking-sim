from __future__ import annotations

from collections.abc import Mapping, Sequence

import pytest
from pydantic import ValidationError

from shepherd_contracts import (
    AlgorithmSpec,
    CameraPlacementMethod,
    DatasetManifest,
    DeerBehaviorModel,
    GroundTruthState,
    JsonValue,
    LocalEnvironmentView,
    Observation,
    RunManifest,
    Tracker,
    TrackingFrame,
)


class ContractOnlyTracker:
    def reset(self, config: Mapping[str, JsonValue], seed: int) -> None:
        pass

    def step(
        self, timestamp_s: float, observations: Sequence[Observation]
    ) -> TrackingFrame:
        return TrackingFrame(timestamp_s=timestamp_s)

    def finalize(self) -> TrackingFrame | None:
        return None


def test_tracker_protocol_is_structural_and_accepts_empty_observations() -> None:
    tracker = ContractOnlyTracker()
    assert isinstance(tracker, Tracker)
    assert tracker.step(4.0, ()).tracks == ()


def test_other_protocols_are_importable() -> None:
    assert CameraPlacementMethod is not None
    assert DeerBehaviorModel is not None
    assert GroundTruthState is not None
    assert LocalEnvironmentView is not None


def test_dataset_manifest_json_round_trip() -> None:
    manifest = DatasetManifest(
        schema_version="1.0",
        case_id="farm-a",
        dataset_id="dataset-001",
        seed=123,
        duration_s=600.0,
        simulation_step_s=0.5,
        scenario_config={"camera_observation_interval_s": 2.0},
        observation_data_ref="datasets/dataset-001/observations.parquet",
        ground_truth_data_ref="datasets/dataset-001/ground_truth.parquet",
    )
    assert DatasetManifest.model_validate_json(manifest.model_dump_json()) == manifest


def test_run_manifest_accepts_json_compatible_configuration() -> None:
    manifest = RunManifest(
        schema_version="1.0",
        case_id="farm-a",
        dataset_id="dataset-001",
        run_id="run-001",
        seed=123,
        algorithm=AlgorithmSpec(
            name="example-tracker",
            version="0.1.0",
            parameters={"thresholds": [1.0, 5.0, 10.0]},
        ),
        input_data_refs=("datasets/dataset-001/observations.parquet",),
        artifact_refs=("runs/run-001/tracks.parquet",),
        environment={"python": "3.10.12"},
    )
    assert manifest.algorithm.parameters["thresholds"] == [1.0, 5.0, 10.0]


def test_manifest_rejects_path_outside_case() -> None:
    with pytest.raises(ValidationError):
        DatasetManifest(
            schema_version="1.0",
            case_id="farm-a",
            dataset_id="dataset-001",
            seed=123,
            duration_s=600.0,
            simulation_step_s=0.5,
            observation_data_ref="../observations.parquet",
            ground_truth_data_ref="datasets/dataset-001/ground_truth.parquet",
        )


def test_dataset_requires_separate_observation_and_truth_data() -> None:
    with pytest.raises(ValidationError):
        DatasetManifest(
            schema_version="1.0",
            case_id="farm-a",
            dataset_id="dataset-001",
            seed=123,
            duration_s=600.0,
            simulation_step_s=0.5,
            observation_data_ref="datasets/dataset-001/data.parquet",
            ground_truth_data_ref="datasets/dataset-001/data.parquet",
        )
