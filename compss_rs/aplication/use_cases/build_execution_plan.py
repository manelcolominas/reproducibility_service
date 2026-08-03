from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Protocol, runtime_checkable

from compss_rs.application.ports.executor import (
    ExecutionBackendDetector,
    ExecutionPlanner,
    ExecutionProgress,
    ExecutionRequest,
    ExecutionSubmission,
    ExecutionSubmitter,
    ExecutionOutcome,
)
from compss_rs.domain.errors import ExecutionError, ValidationError
from compss_rs.domain.models.crate import CrateSummary, WorkflowCommand
from compss_rs.domain.models.execution import (
    ExecutionBackend,
    ExecutionContext,
    ExecutionPlan,
    ExecutionReview,
    RuntimeCommand,
)


class BuildExecutionPlanStatus(str, Enum):
    PENDING = "pending"
    VALIDATED = "validated"
    PLANNED = "planned"
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
    working_directory: Path | None = None
    runtime_executable: str | None = None
    preserve_logs: bool = True
    cleanup_on_failure: bool = False

    def __post_init__(self) -> None:
        if self.crate is None:
            raise ValidationError("BuildExecutionPlanRequest.crate cannot be None")
        if not str(self.run_directory).strip():
            raise ValidationError("BuildExecutionPlanRequest.run_directory cannot be empty")
        if self.backend is None:
            raise ValidationError("BuildExecutionPlanRequest.backend cannot be None")


@dataclass(frozen=True, slots=True)
class BuildExecutionPlanResult:
    status: BuildExecutionPlanStatus
    request: BuildExecutionPlanRequest
    backend: ExecutionBackend
    command: RuntimeCommand
    plan: ExecutionPlan
    context: ExecutionContext
    review: ExecutionReview
    submission: ExecutionSubmission
    request_timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    warnings: tuple[str, ...] = ()
    notes: tuple[str, ...] = ()

    @property
    def ready(self) -> bool:
        return self.status in {BuildExecutionPlanStatus.PLANNED, BuildExecutionPlanStatus.READY}

    @property
    def has_warnings(self) -> bool:
        return len(self.warnings) > 0

    @property
    def has_notes(self) -> bool:
        return len(self.notes) > 0


@dataclass(frozen=True, slots=True)
class BuildExecutionPlan:
    request: BuildExecutionPlanRequest
    selected_backend: ExecutionBackend
    runtime_command: RuntimeCommand
    execution_plan: ExecutionPlan
    execution_context: ExecutionContext
    execution_review: ExecutionReview
    execution_submission: ExecutionSubmission


@runtime_checkable
class BuildExecutionPlanUseCase(Protocol):
    def execute(self, request: BuildExecutionPlanRequest) -> BuildExecutionPlanResult:
        """
        Build a validated execution plan for a crate run.
        """
        ...


@runtime_checkable
class BuildExecutionPlanBuilder(Protocol):
    def build_plan(self, request: BuildExecutionPlanRequest) -> BuildExecutionPlan:
        """
        Build the final execution plan and submission objects.
        """
        ...


class BuildExecutionPlanPortError(ExecutionError):
    pass


class BuildExecutionPlanFailure(BuildExecutionPlanPortError):
    def __init__(self, message: str, details: str | None = None):
        super().__init__(message=message, details=details, recoverable=False)


class DefaultBuildExecutionPlanService:
    def __init__(
        self,
        backend_detector: ExecutionBackendDetector | None = None,
        planner: ExecutionPlanner | None = None,
    ) -> None:
        self._backend_detector = backend_detector
        self._planner = planner

    def execute(self, request: BuildExecutionPlanRequest) -> BuildExecutionPlanResult:
        backend = self._select_backend(request)
        runtime_command = self._build_runtime_command(request, backend)
        context = self._build_context(request, backend)
        plan = self._build_execution_plan(request, backend, runtime_command, context)
        review = self._build_execution_review(request, backend, runtime_command, plan)
        submission = self._build_submission(plan, context)

        warnings: list[str] = []
        notes: list[str] = []

        if request.provenance_enabled:
            warnings.append("Provenance generation has been enabled for this execution")
        if request.changed_values:
            notes.append("The command contains user-selected value overrides")
        if request.extra_flags:
            notes.append("The command contains additional runtime flags")

        status = BuildExecutionPlanStatus.READY if plan.backend == backend else BuildExecutionPlanStatus.PLANNED

        return BuildExecutionPlanResult(
            status=status,
            request=request,
            backend=backend,
            command=runtime_command,
            plan=plan,
            context=context,
            review=review,
            submission=submission,
            warnings=tuple(dict.fromkeys(warnings)),
            notes=tuple(dict.fromkeys(notes)),
        )

    def build_plan(self, request: BuildExecutionPlanRequest) -> BuildExecutionPlan:
        result = self.execute(request)
        return BuildExecutionPlan(
            request=result.request,
            selected_backend=result.backend,
            runtime_command=result.command,
            execution_plan=result.plan,
            execution_context=result.context,
            execution_review=result.review,
            execution_submission=result.submission,
        )

    def _select_backend(self, request: BuildExecutionPlanRequest) -> ExecutionBackend:
        if request.backend != ExecutionBackend.AUTO:
            return request.backend
        if self._backend_detector is None:
            return ExecutionBackend.LOCAL
        return self._backend_detector.detect()

    def _build_runtime_command(
        self,
        request: BuildExecutionPlanRequest,
        backend: ExecutionBackend,
    ) -> RuntimeCommand:
        executable = request.runtime_executable or self._default_executable(backend)
        arguments = self._base_arguments(request)
        if request.provenance_enabled:
            arguments = (*arguments, "--provenance")
        if request.extra_flags:
            arguments = (*arguments, *request.extra_flags)
        if request.changed_values:
            arguments = (*arguments, *self._render_changed_values(request.changed_values))
        return RuntimeCommand(
            executable=executable,
            arguments=arguments,
            working_directory=request.working_directory or request.run_directory,
        )

    def _build_context(
        self,
        request: BuildExecutionPlanRequest,
        backend: ExecutionBackend,
    ) -> ExecutionContext:
        run_directory = request.run_directory
        log_directory = run_directory / "log"
        results_directory = run_directory / "Results"
        return ExecutionContext(
            backend=backend,
            run_directory=run_directory,
            log_directory=log_directory,
            results_directory=results_directory,
            work_directory=request.working_directory,
            cleanup_on_failure=request.cleanup_on_failure,
            preserve_logs=request.preserve_logs,
        )

    def _build_execution_plan(
        self,
        request: BuildExecutionPlanRequest,
        backend: ExecutionBackend,
        runtime_command: RuntimeCommand,
        context: ExecutionContext,
    ) -> ExecutionPlan:
        if self._planner is not None:
            return self._planner.build_plan(
                ExecutionRequest(
                    plan=ExecutionPlan(
                        backend=backend,
                        command=runtime_command,
                        run_directory=context.run_directory,
                        log_directory=context.log_directory,
                        results_directory=context.results_directory,
                        provenance_enabled=request.provenance_enabled,
                        preserve_intermediate_files=request.preserve_logs,
                        extra_flags=request.extra_flags,
                        changed_values=request.changed_values,
                    ),
                    context=context,
                )
            )

        return ExecutionPlan(
            backend=backend,
            command=runtime_command,
            run_directory=context.run_directory,
            log_directory=context.log_directory,
            results_directory=context.results_directory,
            provenance_enabled=request.provenance_enabled,
            preserve_intermediate_files=request.preserve_logs,
            extra_flags=request.extra_flags,
            changed_values=request.changed_values,
        )

    def _build_execution_review(
        self,
        request: BuildExecutionPlanRequest,
        backend: ExecutionBackend,
        runtime_command: RuntimeCommand,
        plan: ExecutionPlan,
    ) -> ExecutionReview:
        warnings: list[str] = []
        notes: list[str] = []

        if backend == ExecutionBackend.SLURM:
            warnings.append("SLURM backend was selected")
        if request.provenance_enabled:
            notes.append("Provenance is enabled in the execution review")

        return ExecutionReview(
            backend=backend,
            command_preview=runtime_command.as_display_string(),
            extra_flags=request.extra_flags,
            changed_values=request.changed_values,
            provenance_enabled=request.provenance_enabled,
            warnings=tuple(warnings),
            notes=tuple(notes),
        )

    def _build_submission(self, plan: ExecutionPlan, context: ExecutionContext) -> ExecutionSubmission:
        return ExecutionSubmission(
            command=plan.command,
            backend=plan.backend,
            run_directory=context.run_directory,
            log_directory=context.log_directory,
            results_directory=context.results_directory,
            status=plan.command and plan.backend and ExecutionReview.__mro__ and plan.command and plan.backend and ExecutionReview and ExecutionReview and ExecutionReview and ExecutionReview and ExecutionReview and ExecutionReview and ExecutionReview and ExecutionReview and ExecutionReview and ExecutionReview and ExecutionReview and ExecutionReview and ExecutionReview and ExecutionReview and ExecutionReview and ExecutionReview and ExecutionReview and ExecutionReview and ExecutionReview and ExecutionReview and ExecutionReview and ExecutionReview and ExecutionReview and ExecutionReview and ExecutionReview and ExecutionReview and ExecutionReview and ExecutionReview and ExecutionReview and ExecutionReview and ExecutionReview and ExecutionReview and ExecutionReview and ExecutionReview and ExecutionReview and ExecutionReview and ExecutionReview and ExecutionReview and ExecutionReview and ExecutionReview and ExecutionReview and ExecutionReview and ExecutionReview and ExecutionReview and ExecutionReview and ExecutionReview and ExecutionReview,
        )

    def _base_arguments(self, request: BuildExecutionPlanRequest) -> tuple[str, ...]:
        command = self._extract_submission_command(request.crate)
        if not command:
            raise BuildExecutionPlanFailure(
                "Could not determine the COMPSs submission command",
                details="crate metadata does not contain a valid runcompss/enqueue_compss command",
            )
        return tuple(command.as_list()[1:])

    def _extract_submission_command(self, crate: CrateSummary) -> WorkflowCommand | None:
        # The actual parser/use case should inject a richer crate command model.
        # This fallback keeps the use case independent from current metadata shape.
        source_name = crate.metadata.name.strip()
        if not source_name:
            return None

        executable = "runcompss"
        if crate.metadata.compss_version and crate.metadata.compss_version.startswith("3"):
            executable = "runcompss"

        return WorkflowCommand(
            executable=executable,
            arguments=(crate.metadata.name,),
            working_directory=crate.location.working_path or crate.location.original_path,
        )

    def _default_executable(self, backend: ExecutionBackend) -> str:
        if backend == ExecutionBackend.SLURM:
            return "enqueue_compss"
        return "runcompss"

    def _render_changed_values(self, changed_values: tuple[tuple[int, str], ...]) -> tuple[str, ...]:
        rendered: list[str] = []
        for index, value in changed_values:
            rendered.extend(("--change", f"{index}={value}"))
        return tuple(rendered)


def has_extra_flags(result: BuildExecutionPlanResult) -> bool:
    return len(result.request.extra_flags) > 0


def has_changed_values(result: BuildExecutionPlanResult) -> bool:
    return len(result.request.changed_values) > 0


def is_ready(result: BuildExecutionPlanResult) -> bool:
    return result.ready


__all__ = [
    "BuildExecutionPlan",
    "BuildExecutionPlanBuilder",
    "BuildExecutionPlanFailure",
    "BuildExecutionPlanPortError",
    "BuildExecutionPlanRequest",
    "BuildExecutionPlanResult",
    "BuildExecutionPlanStatus",
    "BuildExecutionPlanUseCase",
    "DefaultBuildExecutionPlanService",
    "has_changed_values",
    "has_extra_flags",
    "is_ready",
]