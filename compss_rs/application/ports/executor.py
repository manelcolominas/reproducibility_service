from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Protocol, runtime_checkable

from compss_rs.domain.errors import ExecutionError, ValidationError
from compss_rs.domain.models.execution import (
    ExecutionBackend,
    ExecutionContext,
    ExecutionPlan,
    ExecutionResult,
    ExecutionStatus,
    RuntimeCommand,
)


@dataclass(frozen=True, slots=True)
class ExecutionRequest:
    plan: ExecutionPlan
    context: ExecutionContext

    def __post_init__(self) -> None:
        if self.plan.backend != self.context.backend:
            raise ValidationError("ExecutionRequest.plan.backend does not match context.backend")


@dataclass(frozen=True, slots=True)
class ExecutionSubmission:
    command: RuntimeCommand
    backend: ExecutionBackend
    run_directory: Path
    log_directory: Path
    results_directory: Path


@dataclass(frozen=True, slots=True)
class ExecutionOutcome:
    result: ExecutionResult
    submission: ExecutionSubmission

    @property
    def succeeded(self) -> bool:
        return self.result.succeeded

    @property
    def failed(self) -> bool:
        return self.result.failed


@runtime_checkable
class ExecutionBackendDetector(Protocol):
    def detect(self) -> ExecutionBackend:
        ...


@runtime_checkable
class ExecutionPlanner(Protocol):
    def build_plan(self, request: ExecutionRequest) -> ExecutionPlan:
        ...


@runtime_checkable
class ExecutionSubmitter(Protocol):
    def submit(self, submission: ExecutionSubmission) -> ExecutionOutcome:
        ...


class ExecutionPortError(ExecutionError):
    pass


class UnsupportedExecutionBackendError(ExecutionPortError):
    pass


def is_slurm_backend(backend: ExecutionBackend) -> bool:
    return backend == ExecutionBackend.SLURM


def is_local_backend(backend: ExecutionBackend) -> bool:
    return backend == ExecutionBackend.LOCAL