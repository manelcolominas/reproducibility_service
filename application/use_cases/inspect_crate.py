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
import os
import pty
import subprocess
from pathlib import Path

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum

from application.ports.metadata_parser import WorkflowMetadata
from domain.errors import ValidationError
from application.use_cases.import_crate import ImportCrateResult
from domain.models.crate import WorkflowArtifactSummary


class InspectCrateStatus(str, Enum):
    SUCCEEDED = "succeeded"
    FAILED = "failed"

@dataclass(frozen=True, slots=True)
class InspectCrateResult:
    status: InspectCrateStatus
    crate: ImportCrateResult | None = None
    warnings: tuple[str, ...] = ()
    notes: tuple[str, ...] = ()
    inspect_output: str | None = None
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    @property
    def inspected(self) -> bool:
        return self.status == InspectCrateStatus.SUCCEEDED

    @property
    def has_warnings(self) -> bool:
        return len(self.warnings) > 0


def _inspect_rocrate(import_crate_result: ImportCrateResult) -> InspectCrateResult:
    return InspectCrateResult(
        status=InspectCrateStatus.SUCCEEDED,
        crate=import_crate_result,
        notes=("Crate inspection completed",),
    )