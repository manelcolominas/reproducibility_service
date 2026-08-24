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
from enum import Enum
from pathlib import Path


class VerificationState(str, Enum):
    VERIFIED = "verified"
    MISSING = "missing"
    SIZE_MISMATCH = "size_mismatch"
    ACCESS_DENIED = "access_denied"
    NOT_IN_METADATA = "not_in_metadata"
    ERROR = "error"


class VerificationSeverity(str, Enum):
    INFO = "info"
    WARNING = "warning"
    ERROR = "error"


@dataclass(frozen=True, slots=True)
class VerificationIssue:
    code: str
    message: str
    severity: VerificationSeverity = VerificationSeverity.ERROR

    def __post_init__(self) -> None:
        if not self.code.strip():
            raise ValueError("VerificationIssue.code cannot be empty")
        if not self.message.strip():
            raise ValueError("VerificationIssue.message cannot be empty")


@dataclass(frozen=True, slots=True)
class ArtifactReference:
    metadata_name: str
    metadata_id: str
    expected_path: str | None = None

    def __post_init__(self) -> None:
        if not self.metadata_name.strip():
            raise ValueError("ArtifactReference.metadata_name cannot be empty")
        if not self.metadata_id.strip():
            raise ValueError("ArtifactReference.metadata_id cannot be empty")


@dataclass(frozen=True, slots=True)
class ArtifactVerificationResult:
    reference: ArtifactReference
    state: VerificationState
    resolved_path: Path | None = None
    exists: bool = False
    accessible: bool = True
    size_expected: int | None = None
    size_actual: int | None = None
    issues: tuple[VerificationIssue, ...] = ()

    @property
    def is_verified(self) -> bool:
        return self.state == VerificationState.VERIFIED

    @property
    def has_issues(self) -> bool:
        return len(self.issues) > 0

    @property
    def is_error(self) -> bool:
        return self.state in {
            VerificationState.MISSING,
            VerificationState.SIZE_MISMATCH,
            VerificationState.ACCESS_DENIED,
            VerificationState.ERROR,
        }


@dataclass(frozen=True, slots=True)
class VerificationSummary:
    crate_path: Path
    items: tuple[ArtifactVerificationResult, ...] = ()
    created_at: str | None = None

    @property
    def total(self) -> int:
        return len(self.items)

    @property
    def verified(self) -> int:
        return sum(1 for item in self.items if item.state == VerificationState.VERIFIED)

    @property
    def failed(self) -> int:
        return sum(1 for item in self.items if item.is_error)

    @property
    def warnings(self) -> int:
        return sum(
            1
            for item in self.items
            if any(issue.severity == VerificationSeverity.WARNING for issue in item.issues)
        )

    @property
    def has_failures(self) -> bool:
        return self.failed > 0