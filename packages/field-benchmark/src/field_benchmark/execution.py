from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
import json
import hashlib
from pathlib import Path
from uuid import uuid4

from field_environment import resolve_case_path, validate_case_id


class ExecutionStatus(str, Enum):
    PENDING = "PENDING"
    RUNNING = "RUNNING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"


@dataclass(frozen=True)
class ExecutionCondition:
    dataset_id: str
    layout_id: str
    tracker_method: str
    benchmark_id: str | None = None

    @property
    def run_id(self) -> str:
        base = f"{self.dataset_id}__{self.layout_id}__{self.tracker_method}"
        return base if self.benchmark_id is None else f"{self.benchmark_id}__{base}"

    @property
    def condition_id(self) -> str:
        return self.run_id


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class BenchmarkExecutionJournal:
    def __init__(
        self,
        cases_root: str | Path,
        *,
        case_id: str,
        benchmark_id: str,
        conditions: tuple[ExecutionCondition, ...],
        configuration: dict | None = None,
    ) -> None:
        validate_case_id(benchmark_id)
        self.case_id = case_id
        self.benchmark_id = benchmark_id
        self.directory = (
            resolve_case_path(cases_root, case_id) / "benchmarks" / benchmark_id
        )
        self.path = self.directory / "execution_manifest.json"
        configuration_payload = configuration or {}
        configuration_text = json.dumps(
            configuration_payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")
        )
        configuration_sha256 = hashlib.sha256(configuration_text.encode("utf-8")).hexdigest()
        self.directory.mkdir(parents=True, exist_ok=True)
        if self.path.is_file():
            self.document = json.loads(self.path.read_text(encoding="utf-8"))
            if self.document.get("case_id") != case_id:
                raise ValueError("execution manifest case_id does not match")
            stored_sha256 = self.document.get("configuration_sha256")
            if stored_sha256 is not None and stored_sha256 != configuration_sha256:
                raise ValueError(
                    "benchmark_id already exists with different experiment configuration; "
                    "use a new benchmark_id"
                )
            if stored_sha256 is None:
                self.document["configuration"] = configuration_payload
                self.document["configuration_sha256"] = configuration_sha256
            existing = self.document.setdefault("conditions", {})
            for item in existing.values():
                if item.get("status") == ExecutionStatus.RUNNING.value:
                    item["status"] = ExecutionStatus.PENDING.value
                    item["error"] = "previous execution was interrupted"
        else:
            self.document = {
                "schema_version": "1.0",
                "case_id": case_id,
                "benchmark_id": benchmark_id,
                "created_at": _now(),
                "updated_at": _now(),
                "configuration": configuration_payload,
                "configuration_sha256": configuration_sha256,
                "conditions": {},
            }
        for condition in conditions:
            self.document["conditions"].setdefault(
                condition.condition_id,
                {
                    "dataset_id": condition.dataset_id,
                    "layout_id": condition.layout_id,
                    "tracker_method": condition.tracker_method,
                    "run_id": condition.run_id,
                    "status": ExecutionStatus.PENDING.value,
                    "error": None,
                },
            )
        self.save()

    def status(self, condition: ExecutionCondition) -> ExecutionStatus:
        value = self.document["conditions"][condition.condition_id]["status"]
        return ExecutionStatus(value)

    def mark_running(self, condition: ExecutionCondition) -> None:
        self._mark(condition, ExecutionStatus.RUNNING, error=None, started_at=_now())

    def mark_completed(self, condition: ExecutionCondition) -> None:
        self._mark(condition, ExecutionStatus.COMPLETED, error=None, completed_at=_now())

    def mark_failed(self, condition: ExecutionCondition, error: BaseException) -> None:
        self._mark(
            condition,
            ExecutionStatus.FAILED,
            error=f"{type(error).__name__}: {error}",
            completed_at=_now(),
        )

    def record_generation(self, statuses: dict[str, str]) -> None:
        generation = self.document.setdefault("generation_conditions", {})
        for condition_id, status in statuses.items():
            completed = status == "completed"
            generation[condition_id] = {
                "status": (
                    ExecutionStatus.COMPLETED.value
                    if completed
                    else ExecutionStatus.FAILED.value
                ),
                "error": None if completed else status,
                "completed_at": _now(),
            }
        self.save()

    def _mark(self, condition: ExecutionCondition, status: ExecutionStatus, **values) -> None:
        item = self.document["conditions"][condition.condition_id]
        item["status"] = status.value
        item.update(values)
        self.save()

    def save(self) -> None:
        self.document["updated_at"] = _now()
        temporary = self.path.with_name(f".{self.path.name}.{uuid4().hex}.tmp")
        temporary.write_text(
            json.dumps(self.document, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        temporary.replace(self.path)
