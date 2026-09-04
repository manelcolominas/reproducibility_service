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

from domain.models.execution import (
    ExecutionBackend,
    ExecutionResult,
    RuntimeCommand,
)

# DO NOT DELETE
@dataclass(frozen=True, slots=True)
class ExecutionSubmission:
    command: RuntimeCommand
    backend: ExecutionBackend
    workspace_directory: Path
    log_directory: Path
    results_directory: Path

    @property
    def execution_directory(self) -> Path:
        return self.results_directory

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