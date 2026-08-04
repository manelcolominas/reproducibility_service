from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
import shlex
from typing import Protocol, runtime_checkable

from compss_rs.application.ports.executor import (
    ExecutionBackendDetector,
    ExecutionPlanner as ExecutorPlanner,
    ExecutionRequest,
    ExecutionSubmission,
)
from compss_rs.domain.errors import CommandBuildError, ValidationError
from compss_rs.domain.models.crate import CrateSummary, WorkflowCommand
from compss_rs.domain.models.execution import (
    ExecutionBackend,
    ExecutionContext,
    ExecutionPlan,
    RuntimeCommand,
)


class BuildExecutionPlanStatus(str, Enum):
    PENDING = "pending"
    READY = "ready"
    FAILED = "failed"


@dataclass(frozen=True, slots=True)
class BuildExecutionPlanRequest:
    crate: CrateSummary
    run_directory: Path
    backend: ExecutionBackend = ExecutionBackend.AUTO
    provenance_enabled: bool = False
    extra_flags: tuple[str, ...] = ()
    changed_values: tuple[tuple[int, str], ...] = ()
    submission_command: str | None = None
    runtime_executable: str | None = None

    def __post_init__(self) -> None:
        if self.crate is None:
            raise ValidationError("BuildExecutionPlanRequest.crate cannot be None")
        if not str(self.run_directory).strip():
            raise ValidationError("BuildExecutionPlanRequest.run_directory cannot be empty")


@dataclass(frozen=True, slots=True)
class BuildExecutionPlanResult:
    status: BuildExecutionPlanStatus
    request: BuildExecutionPlanRequest
    backend: ExecutionBackend
    command: RuntimeCommand
    plan: ExecutionPlan
    context: ExecutionContext
    submission: ExecutionSubmission
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    warnings: tuple[str, ...] = ()
    notes: tuple[str, ...] = ()

    @property
    def ready(self) -> bool:
        return self.status == BuildExecutionPlanStatus.READY


@runtime_checkable
class BuildExecutionPlanUseCase(Protocol):
    def execute(self, request: BuildExecutionPlanRequest) -> BuildExecutionPlanResult:
        ...


class BuildExecutionPlanPortError(CommandBuildError):
    pass


class BuildExecutionPlanFailure(BuildExecutionPlanPortError):
    pass


class DefaultBuildExecutionPlanService:
    def __init__(self, backend_detector: ExecutionBackendDetector | None = None) -> None:
        self._backend_detector = backend_detector

    def execute(self, request: BuildExecutionPlanRequest) -> BuildExecutionPlanResult:
        backend = self._select_backend(request)
        command = self._build_command(request, backend)
        context = self._build_context(request, backend)
        plan = ExecutionPlan(
            backend=backend,
            command=command,
            context=context,
            provenance_enabled=request.provenance_enabled,
            extra_flags=request.extra_flags,
            changed_values=request.changed_values,
        )
        submission = ExecutionSubmission(
            command=command,
            backend=backend,
            run_directory=context.run_directory,
            log_directory=context.log_directory,
            results_directory=context.results_directory,
        )

        warnings: list[str] = []
        notes: list[str] = []

        if request.provenance_enabled:
            notes.append("Provenance is enabled")
        if request.extra_flags:
            notes.append("Extra runtime flags were added")

        return BuildExecutionPlanResult(
            status=BuildExecutionPlanStatus.READY,
            request=request,
            backend=backend,
            command=command,
            plan=plan,
            context=context,
            submission=submission,
            warnings=tuple(warnings),
            notes=tuple(notes),
        )

    def _select_backend(self, request: BuildExecutionPlanRequest) -> ExecutionBackend:
        if request.backend != ExecutionBackend.AUTO:
            return request.backend
        if self._backend_detector is None:
            return ExecutionBackend.LOCAL
        return self._backend_detector.detect()

    def _build_context(
        self,
        request: BuildExecutionPlanRequest,
        backend: ExecutionBackend,
    ) -> ExecutionContext:
        return ExecutionContext(
            backend=backend,
            run_directory=request.run_directory,
            log_directory=request.run_directory / "log",
            results_directory=request.run_directory / "Results",
        )

    def _build_command(
        self,
        request: BuildExecutionPlanRequest,
        backend: ExecutionBackend,
    ) -> RuntimeCommand:
        raw_command = request.submission_command or self._discover_command(request.crate)
        if not raw_command:
            raise BuildExecutionPlanFailure("Could not determine the submission command")

        parts = shlex.split(raw_command)
        executable = request.runtime_executable or self._default_executable(backend)

        if not parts:
            raise BuildExecutionPlanFailure("The submission command is empty")

        parts[0] = executable

        arguments = list(parts[1:])
        if request.provenance_enabled:
            arguments.insert(0, "--provenance")
        if request.extra_flags:
            arguments = list(request.extra_flags) + arguments
        if request.changed_values:
            for index, value in request.changed_values:
                arguments.extend(["--change", f"{index}={value}"])

        return RuntimeCommand(
            executable=parts[0],
            arguments=tuple(arguments),
            working_directory=request.run_directory,
        )

    def _discover_command(self, crate: CrateSummary) -> str | None:
        submission_file = crate.location.working_path / "compss_submission_command_line.txt"
        if submission_file.exists():
            content = submission_file.read_text(encoding="utf-8").strip()
            return content or None
        return None

    def _default_executable(self, backend: ExecutionBackend) -> str:
        return "enqueue_compss" if backend == ExecutionBackend.SLURM else "runcompss"