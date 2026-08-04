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
            raise ValidationError(
                message="ExecutionRequest plan backend does not match context backend",
                details=f"plan={self.plan.backend.value}, context={self.context.backend.value}",
            )


@dataclass(frozen=True, slots=True)
class ExecutionProgress:
    message: str
    percent: float | None = None
    current_step: str | None = None
    completed_steps: tuple[str, ...] = ()
    total_steps: int | None = None

    def __post_init__(self) -> None:
        if not self.message.strip():
            raise ValidationError("ExecutionProgress.message cannot be empty")
        if self.percent is not None and not 0.0 <= self.percent <= 100.0:
            raise ValidationError("ExecutionProgress.percent must be between 0 and 100")
        if self.total_steps is not None and self.total_steps < 0:
            raise ValidationError("ExecutionProgress.total_steps cannot be negative")


@dataclass(frozen=True, slots=True)
class ExecutionSubmission:
    command: RuntimeCommand
    backend: ExecutionBackend
    run_directory: Path
    log_directory: Path
    results_directory: Path
    status: ExecutionStatus = ExecutionStatus.PENDING
    job_id: str | None = None
    dry_run: bool = False

    def __post_init__(self) -> None:
        if not str(self.run_directory).strip():
            raise ValidationError("ExecutionSubmission.run_directory cannot be empty")
        if not str(self.log_directory).strip():
            raise ValidationError("ExecutionSubmission.log_directory cannot be empty")
        if not str(self.results_directory).strip():
            raise ValidationError("ExecutionSubmission.results_directory cannot be empty")


@dataclass(frozen=True, slots=True)
class ExecutionOutcome:
    result: ExecutionResult
    submission: ExecutionSubmission
    runtime_message: str = ""
    warnings: tuple[str, ...] = ()
    artifacts: tuple[Path, ...] = ()

    @property
    def succeeded(self) -> bool:
        return self.result.succeeded

    @property
    def failed(self) -> bool:
        return self.result.failed


@runtime_checkable
class ExecutionBackendDetector(Protocol):
    def detect(self) -> ExecutionBackend:
        """
        Determine the most appropriate backend for the current environment.
        """
        ...


@runtime_checkable
class ExecutionPlanner(Protocol):
    def build_plan(self, request: ExecutionRequest) -> ExecutionPlan:
        """
        Build a validated execution plan from a request.
        """
        ...


@runtime_checkable
class ExecutionSubmitter(Protocol):
    def submit(self, submission: ExecutionSubmission) -> ExecutionOutcome:
        """
        Submit a prepared command to the selected runtime backend.
        """
        ...


@runtime_checkable
class ExecutionMonitor(Protocol):
    def status(self, submission: ExecutionSubmission) -> ExecutionStatus:
        """
        Return the current execution status for a submitted job.
        """
        ...


@runtime_checkable
class ExecutionCanceller(Protocol):
    def cancel(self, submission: ExecutionSubmission) -> None:
        """
        Cancel a running submission.
        """
        ...


@runtime_checkable
class ExecutionLogCollector(Protocol):
    def collect(self, submission: ExecutionSubmission) -> tuple[Path, ...]:
        """
        Return the log files associated with a submission.
        """
        ...


class ExecutionPortError(ExecutionError):
    pass


class UnsupportedExecutionBackendError(ExecutionPortError):
    def __init__(self, backend: str, details: str | None = None):
        super().__init__(
            message=f"Unsupported execution backend: {backend}",
            details=details,
            recoverable=False,
        )


def is_slurm_backend(backend: ExecutionBackend) -> bool:
    return backend == ExecutionBackend.SLURM


def is_local_backend(backend: ExecutionBackend) -> bool:
    return backend == ExecutionBackend.LOCAL


__all__ = [
    "ExecutionBackendDetector",
    "ExecutionCanceller",
    "ExecutionLogCollector",
    "ExecutionMonitor",
    "ExecutionOutcome",
    "ExecutionPlanner",
    "ExecutionPortError",
    "ExecutionProgress",
    "ExecutionRequest",
    "ExecutionSubmission",
    "ExecutionSubmitter",
    "UnsupportedExecutionBackendError",
    "is_local_backend",
    "is_slurm_backend",
]