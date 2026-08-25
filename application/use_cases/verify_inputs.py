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

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Protocol, runtime_checkable

from infrastructure.adapters import LocalFileSystem
from domain.errors import FileSystemError, ValidationError
from domain.models.crate import CrateSummary, WorkflowArtifact
from domain.models.verification import (
    ArtifactReference,
    ArtifactVerificationResult,
    VerificationIssue,
    VerificationSeverity,
    VerificationState,
    VerificationSummary,
)
from domain.models.crate import CrateSummary


class VerifyInputsStatus(str, Enum):
    PENDING = "pending"
    CHECKING = "checking"
    VERIFIED = "verified"
    WARNING = "warning"
    FAILED = "failed"


@dataclass(frozen=True, slots=True)
class VerifyInputsRequest:
    crate: CrateSummary
    fail_fast: bool = False

    def __post_init__(self) -> None:
        if self.crate is None:
            raise ValidationError("VerifyInputsRequest.crate cannot be None")



@dataclass(frozen=True, slots=True)
class VerifyInputsResult:
    status: VerifyInputsStatus
    request: VerifyInputsRequest
    summary: VerificationSummary
    checked_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    warnings: tuple[str, ...] = ()
    notes: tuple[str, ...] = ()

    @property
    def verified(self) -> bool:
        return self.status == VerifyInputsStatus.VERIFIED

    @property
    def has_warnings(self) -> bool:
        return len(self.warnings) > 0


@runtime_checkable
class VerifyInputsUseCase(Protocol):
    def execute(self, request: VerifyInputsRequest) -> VerifyInputsResult:
        ...


def _verify_rocrate_simple(crate: CrateSummary, file_system: LocalFileSystem) -> VerifyInputsResult:
    request = VerifyInputsRequest(crate=crate)

    base_path = crate.location.crate_path
    results: list[ArtifactVerificationResult] = []
    warnings: list[str] = []
    notes: list[str] = []

    for artifact in crate.all_artifacts:
        reference = ArtifactReference(
            metadata_name=artifact.name,
            metadata_id=artifact.metadata_id or artifact.path,
            expected_path=artifact.path,
        )

        resolved_path = (
            base_path / reference.expected_path
            if reference.expected_path
            else base_path / reference.metadata_id
        )

        if not file_system.exists(resolved_path):
            issue = VerificationIssue(
                code="missing",
                message=f"Artifact not found: {resolved_path}",
                severity=VerificationSeverity.ERROR,
            )
            result = ArtifactVerificationResult(
                reference=reference,
                state=VerificationState.MISSING,
                resolved_path=resolved_path,
                exists=False,
                accessible=False,
                issues=(issue,),
            )
        else:
            metadata = file_system.metadata(resolved_path)
            if not metadata.readable:
                issue = VerificationIssue(
                    code="access-denied",
                    message=f"Artifact is not readable: {resolved_path}",
                    severity=VerificationSeverity.ERROR,
                )
                result = ArtifactVerificationResult(
                    reference=reference,
                    state=VerificationState.ACCESS_DENIED,
                    resolved_path=resolved_path,
                    exists=True,
                    accessible=False,
                    issues=(issue,),
                )
            else:
                result = ArtifactVerificationResult(
                    reference=reference,
                    state=VerificationState.VERIFIED,
                    resolved_path=resolved_path,
                    exists=True,
                    accessible=True,
                    size_actual=metadata.size_bytes,
                )

        results.append(result)

        if result.has_issues:
            notes.extend(issue.message for issue in result.issues)
        if result.state == VerificationState.SIZE_MISMATCH:
            warnings.append(f"Size mismatch for {artifact.name}")

    summary = VerificationSummary(
        crate_path=base_path,
        items=tuple(results),
    )

    if summary.has_failures:
        status = VerifyInputsStatus.FAILED
    elif summary.warnings > 0:
        status = VerifyInputsStatus.WARNING
    else:
        status = VerifyInputsStatus.VERIFIED

    return VerifyInputsResult(
        status=status,
        request=request,
        summary=summary,
        warnings=tuple(dict.fromkeys(warnings)),
        notes=tuple(dict.fromkeys(notes)),
    )