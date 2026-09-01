#!/usr/bin/env python3
#
#  Copyright 2002-2026 Barcelona Supercomputing Center (www.bsc.es)
#
#  Licensed under the Apache License, Version 2.0 (the "License");
#  you may not use this file except in compliance with the License.
#  You may obtain a copy of the License at
#
#      http://www.apache.org/licenses/LICENSE-2.0
#
#  Unless required by applicable law or agreed to in writing, software
#  distributed under the License is distributed on an "AS IS" BASIS,
#  WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
#  See the License for the specific language governing permissions and
#  limitations under the License.
#

from __future__ import annotations

from dataclasses import dataclass, field, replace
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path


class ExecutionBackend(str, Enum):
    AUTO = "auto"
    LOCAL = "local"
    SLURM = "slurm"


class ExecutionStatus(str, Enum):
    READY = "ready"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    CANCELLED = "cancelled"


@dataclass(frozen=True, slots=True)
class RuntimeCommand:
    executable: str
    arguments: tuple[str, ...] = ()
    working_directory: Path | None = None

    def __post_init__(self) -> None:
        if not self.executable.strip():
            raise ValueError("RuntimeCommand.executable cannot be empty")

    def as_list(self) -> list[str]:
        return [self.executable, *self.arguments]

    def as_string(self) -> str:
        return " ".join(self.as_list())

    def with_arguments(self, arguments: tuple[str, ...]) -> RuntimeCommand:
        return replace(self, arguments=self.arguments + arguments)


@dataclass(frozen=True, slots=True)
class ExecutionContext:
    backend: ExecutionBackend
    workspace_directory: Path
    log_directory: Path
    results_directory: Path

    @property
    def execution_directory(self) -> Path:
        return self.results_directory

    @property
    def working_directory(self) -> Path:
        return self.results_directory

    def __post_init__(self) -> None:
        if not str(self.workspace_directory).strip():
            raise ValueError("ExecutionContext.workspace_directory cannot be empty")
        if not str(self.log_directory).strip():
            raise ValueError("ExecutionContext.log_directory cannot be empty")
        if not str(self.results_directory).strip():
            raise ValueError("ExecutionContext.results_directory cannot be empty")


@dataclass(frozen=True, slots=True)
class ExecutionPlan:
    backend: ExecutionBackend
    command: RuntimeCommand
    context: ExecutionContext
    provenance_enabled: bool = False

    @property
    def command_line(self) -> list[str]:
        return self.command.as_list()


@dataclass(frozen=True, slots=True)
class ExecutionLog:
    stdout_path: Path
    stderr_path: Path

    def __post_init__(self) -> None:
        if not str(self.stdout_path).strip():
            raise ValueError("ExecutionLog.stdout_path cannot be empty")
        if not str(self.stderr_path).strip():
            raise ValueError("ExecutionLog.stderr_path cannot be empty")


@dataclass(frozen=True, slots=True)
class ExecutionResult:
    status: ExecutionStatus
    command: RuntimeCommand
    context: ExecutionContext
    log: ExecutionLog
    return_code: int | None = None
    started_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    finished_at: datetime | None = None
    summary_message: str = ""
    error_message: str | None = None
    generated_ro_crate_path: Path | None = None

    @property
    def succeeded(self) -> bool:
        return self.status == ExecutionStatus.SUCCEEDED

    @property
    def failed(self) -> bool:
        return self.status == ExecutionStatus.FAILED