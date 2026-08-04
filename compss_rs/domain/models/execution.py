from __future__ import annotations

from dataclasses import dataclass, field, replace
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Mapping, Sequence


class ExecutionBackend(str, Enum):
    AUTO = "auto"
    LOCAL = "local"
    SLURM = "slurm"
    REMOTE = "remote"
    CUSTOM = "custom"


class ExecutionStatus(str, Enum):
    PENDING = "pending"
    READY = "ready"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    CANCELLED = "cancelled"
    SKIPPED = "skipped"


class LogStream(str, Enum):
    STDOUT = "stdout"
    STDERR = "stderr"
    COMBINED = "combined"


@dataclass(frozen=True, slots=True)
class RuntimeCommand:
    executable: str
    arguments: tuple[str, ...] = ()
    working_directory: Path | None = None
    environment: Mapping[str, str] = field(default_factory=dict)
    use_shell: bool = False

    def __post_init__(self) -> None:
        if not self.executable.strip():
            raise ValueError("RuntimeCommand.executable cannot be empty")
        if not all(argument is not None for argument in self.arguments):
            raise ValueError("RuntimeCommand.arguments cannot contain None")

    def as_list(self) -> list[str]:
        return [self.executable, *self.arguments]

    def as_display_string(self) -> str:
        return " ".join(self.as_list())

    def with_argument(self, argument: str) -> RuntimeCommand:
        if not argument.strip():
            raise ValueError("argument cannot be empty")
        return replace(self, arguments=self.arguments + (argument,))

    def with_arguments(self, arguments: Sequence[str]) -> RuntimeCommand:
        return replace(self, arguments=self.arguments + tuple(arguments))

    def with_working_directory(self, working_directory: Path) -> RuntimeCommand:
        return replace(self, working_directory=working_directory)

    def with_environment(self, environment: Mapping[str, str]) -> RuntimeCommand:
        return replace(self, environment=dict(environment))


@dataclass(frozen=True, slots=True)
class ExecutionPlan:
    backend: ExecutionBackend
    command: RuntimeCommand
    run_directory: Path
    log_directory: Path | None = None
    results_directory: Path | None = None
    provenance_enabled: bool = False
    preserve_intermediate_files: bool = True
    extra_flags: tuple[str, ...] = ()
    changed_values: tuple[tuple[int, str], ...] = ()
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    def __post_init__(self) -> None:
        if self.backend == ExecutionBackend.AUTO:
            return
        if not self.command.executable.strip():
            raise ValueError("ExecutionPlan.command.executable cannot be empty")
        if not str(self.run_directory).strip():
            raise ValueError("ExecutionPlan.run_directory cannot be empty")

    @property
    def command_line(self) -> list[str]:
        return self.command.as_list()

    @property
    def display_command(self) -> str:
        return self.command.as_display_string()

    def with_command(self, command: RuntimeCommand) -> ExecutionPlan:
        return replace(self, command=command)

    def with_extra_flags(self, flags: Sequence[str]) -> ExecutionPlan:
        return replace(self, extra_flags=self.extra_flags + tuple(flags))

    def with_changed_value(self, index: int, value: str) -> ExecutionPlan:
        if index < 0:
            raise ValueError("index must be >= 0")
        if not value.strip():
            raise ValueError("value cannot be empty")
        return replace(self, changed_values=self.changed_values + ((index, value),))

    def with_provenance(self, enabled: bool) -> ExecutionPlan:
        return replace(self, provenance_enabled=enabled)

    def with_results_directory(self, results_directory: Path) -> ExecutionPlan:
        return replace(self, results_directory=results_directory)

    def with_log_directory(self, log_directory: Path) -> ExecutionPlan:
        return replace(self, log_directory=log_directory)


@dataclass(frozen=True, slots=True)
class ExecutionLog:
    stream: LogStream
    path: Path
    size_bytes: int | None = None
    created_at: datetime | None = None

    def __post_init__(self) -> None:
        if not str(self.path).strip():
            raise ValueError("ExecutionLog.path cannot be empty")
        if self.size_bytes is not None and self.size_bytes < 0:
            raise ValueError("ExecutionLog.size_bytes cannot be negative")


@dataclass(frozen=True, slots=True)
class ExecutionResult:
    status: ExecutionStatus
    backend: ExecutionBackend
    run_directory: Path
    command: RuntimeCommand
    started_at: datetime
    finished_at: datetime | None = None
    return_code: int | None = None
    logs: tuple[ExecutionLog, ...] = ()
    output_paths: tuple[Path, ...] = ()
    summary_message: str = ""
    error_message: str | None = None

    def __post_init__(self) -> None:
        if not str(self.run_directory).strip():
            raise ValueError("ExecutionResult.run_directory cannot be empty")
        if self.status == ExecutionStatus.SUCCEEDED and self.return_code not in {0, None}:
            raise ValueError("A succeeded execution cannot have a non-zero return code")
        if self.status == ExecutionStatus.FAILED and self.return_code == 0:
            raise ValueError("A failed execution cannot have a zero return code")

    @property
    def succeeded(self) -> bool:
        return self.status == ExecutionStatus.SUCCEEDED

    @property
    def failed(self) -> bool:
        return self.status == ExecutionStatus.FAILED

    @property
    def cancelled(self) -> bool:
        return self.status == ExecutionStatus.CANCELLED

    def with_log(self, log: ExecutionLog) -> ExecutionResult:
        return replace(self, logs=self.logs + (log,))

    def with_output_path(self, path: Path) -> ExecutionResult:
        return replace(self, output_paths=self.output_paths + (path,))

    def with_finished_at(self, finished_at: datetime) -> ExecutionResult:
        return replace(self, finished_at=finished_at)

    def with_return_code(self, return_code: int) -> ExecutionResult:
        return replace(self, return_code=return_code)


@dataclass(frozen=True, slots=True)
class ExecutionContext:
    backend: ExecutionBackend
    run_directory: Path
    log_directory: Path
    results_directory: Path
    work_directory: Path | None = None
    cleanup_on_failure: bool = False
    preserve_logs: bool = True

    def __post_init__(self) -> None:
        for field_name in ("run_directory", "log_directory", "results_directory"):
            if not str(getattr(self, field_name)).strip():
                raise ValueError(f"ExecutionContext.{field_name} cannot be empty")

    def with_work_directory(self, work_directory: Path | None) -> ExecutionContext:
        return replace(self, work_directory=work_directory)

    def with_cleanup_on_failure(self, cleanup_on_failure: bool) -> ExecutionContext:
        return replace(self, cleanup_on_failure=cleanup_on_failure)


@dataclass(frozen=True, slots=True)
class ExecutionReview:
    backend: ExecutionBackend
    command_preview: str
    extra_flags: tuple[str, ...] = ()
    changed_values: tuple[tuple[int, str], ...] = ()
    provenance_enabled: bool = False
    warnings: tuple[str, ...] = ()
    notes: tuple[str, ...] = ()

    def with_warning(self, warning: str) -> ExecutionReview:
        if not warning.strip():
            raise ValueError("warning cannot be empty")
        return replace(self, warnings=self.warnings + (warning,))

    def with_note(self, note: str) -> ExecutionReview:
        if not note.strip():
            raise ValueError("note cannot be empty")
        return replace(self, notes=self.notes + (note,))


__all__ = [
    "ExecutionBackend",
    "ExecutionContext",
    "ExecutionLog",
    "ExecutionPlan",
    "ExecutionResult",
    "ExecutionReview",
    "ExecutionStatus",
    "LogStream",
    "RuntimeCommand",
]