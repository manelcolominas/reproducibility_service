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

from dataclasses import dataclass
from pathlib import Path
from typing import Protocol, runtime_checkable

from domain.errors import ExecutionError, ValidationError
from domain.models.execution import (
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
    workspace_directory: Path
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