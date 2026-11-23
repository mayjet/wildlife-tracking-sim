from __future__ import annotations

import json
import pytest

from field_benchmark import (
    BenchmarkExecutionJournal,
    ExecutionCondition,
    ExecutionStatus,
)


def test_execution_journal_recovers_interrupted_condition(tmp_path) -> None:
    condition = ExecutionCondition("dataset-1", "layout-1", "constant_velocity")
    journal = BenchmarkExecutionJournal(
        tmp_path, case_id="case-1", benchmark_id="benchmark-1", conditions=(condition,)
    )
    assert journal.status(condition) is ExecutionStatus.PENDING
    journal.mark_running(condition)
    recovered = BenchmarkExecutionJournal(
        tmp_path, case_id="case-1", benchmark_id="benchmark-1", conditions=(condition,)
    )
    assert recovered.status(condition) is ExecutionStatus.PENDING
    document = json.loads(recovered.path.read_text(encoding="utf-8"))
    assert document["conditions"][condition.condition_id]["error"] == (
        "previous execution was interrupted"
    )


def test_execution_journal_records_failure_and_completion(tmp_path) -> None:
    failed = ExecutionCondition("dataset-1", "layout-1", "last_observation")
    completed = ExecutionCondition("dataset-1", "layout-1", "constant_velocity")
    journal = BenchmarkExecutionJournal(
        tmp_path,
        case_id="case-1",
        benchmark_id="benchmark-1",
        conditions=(failed, completed),
    )
    journal.mark_failed(failed, RuntimeError("broken"))
    journal.mark_completed(completed)
    assert journal.status(failed) is ExecutionStatus.FAILED
    assert journal.status(completed) is ExecutionStatus.COMPLETED


def test_execution_condition_is_scoped_by_benchmark() -> None:
    condition = ExecutionCondition(
        "dataset-1", "layout-1", "constant_velocity", "benchmark-1"
    )
    assert condition.run_id.startswith("benchmark-1__")


def test_execution_journal_rejects_changed_configuration(tmp_path) -> None:
    condition = ExecutionCondition("dataset-1", "layout-1", "constant_velocity")
    BenchmarkExecutionJournal(
        tmp_path,
        case_id="case-1",
        benchmark_id="benchmark-1",
        conditions=(condition,),
        configuration={"seed": 1},
    )
    with pytest.raises(ValueError, match="new benchmark_id"):
        BenchmarkExecutionJournal(
            tmp_path,
            case_id="case-1",
            benchmark_id="benchmark-1",
            conditions=(condition,),
            configuration={"seed": 2},
        )
