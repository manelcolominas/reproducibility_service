from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Iterable


class VerificationState(str, Enum):
    VERIFIED = "verified"
    MISSING = "missing"
    SIZE_MISMATCH = "size_mismatch"
    MODIFIED_TIME_MISMATCH = "modified_time_mismatch"
    ACCESS_DENIED = "access_denied"
    NOT_IN_METADATA = "not_in_metadata"
    SKIPPED = "skipped"
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
    details: str | None = None

    def __post_init__(self) -> None:
        if not self.code.strip():
            raise ValueError("VerificationIssue.code cannot be empty")
        if not self.message.strip():
            raise ValueError("VerificationIssue.message cannot be empty")


@dataclass(frozen=True, slots=True)
class ArtifactReference:
    metadata_name: str
    metadata_id: str
    expected_relative_path: str | None = None
    source_kind: str = "file"

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
    modified_time_expected: datetime | None = None
    modified_time_actual: datetime | None = None
    issues: tuple[VerificationIssue, ...] = field(default_factory=tuple)

    def __post_init__(self) -> None:
        if self.state == VerificationState.VERIFIED and not self.exists:
            raise ValueError("A verified artifact must exist")
        if self.state == VerificationState.MISSING and self.exists:
            raise ValueError("A missing artifact cannot exist")

    @property
    def is_verified(self) -> bool:
        return self.state == VerificationState.VERIFIED

    @property
    def has_issues(self) -> bool:
        return len(self.issues) > 0

    @property
    def is_warning(self) -> bool:
        return any(issue.severity == VerificationSeverity.WARNING for issue in self.issues)

    @property
    def is_error(self) -> bool:
        return self.state in {
            VerificationState.MISSING,
            VerificationState.SIZE_MISMATCH,
            VerificationState.MODIFIED_TIME_MISMATCH,
            VerificationState.ACCESS_DENIED,
            VerificationState.ERROR,
        } or any(issue.severity == VerificationSeverity.ERROR for issue in self.issues)


@dataclass(frozen=True, slots=True)
class VerificationPolicy:
    verify_content_size: bool = True
    verify_modified_time: bool = True
    verify_accessibility: bool = True
    allow_remote_artifacts: bool = True
    fail_fast: bool = False

    def __post_init__(self) -> None:
        if not self.allow_remote_artifacts and not self.verify_accessibility:
            raise ValueError("verify_accessibility cannot be disabled when remote artifacts are disallowed")


@dataclass(frozen=True, slots=True)
class VerificationSummary:
    crate_path: Path
    policy: VerificationPolicy
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    items: tuple[ArtifactVerificationResult, ...] = field(default_factory=tuple)
    remote_artifacts_present: bool = False
    data_persistence: bool = True
    crate_version: str | None = None
    compss_version: str | None = None

    def __post_init__(self) -> None:
        if not str(self.crate_path).strip():
            raise ValueError("VerificationSummary.crate_path cannot be empty")

    @property
    def total_items(self) -> int:
        return len(self.items)

    @property
    def verified_items(self) -> int:
        return sum(1 for item in self.items if item.state == VerificationState.VERIFIED)

    @property
    def failed_items(self) -> int:
        return sum(1 for item in self.items if item.is_error)

    @property
    def warning_items(self) -> int:
        return sum(1 for item in self.items if item.is_warning)

    @property
    def skipped_items(self) -> int:
        return sum(1 for item in self.items if item.state == VerificationState.SKIPPED)

    @property
    def has_failures(self) -> bool:
        return self.failed_items > 0

    @property
    def has_warnings(self) -> bool:
        return self.warning_items > 0

    def with_item(self, item: ArtifactVerificationResult) -> VerificationSummary:
        return VerificationSummary(
            crate_path=self.crate_path,
            policy=self.policy,
            created_at=self.created_at,
            items=self.items + (item,),
            remote_artifacts_present=self.remote_artifacts_present,
            data_persistence=self.data_persistence,
            crate_version=self.crate_version,
            compss_version=self.compss_version,
        )

    def extend(self, items: Iterable[ArtifactVerificationResult]) -> VerificationSummary:
        return VerificationSummary(
            crate_path=self.crate_path,
            policy=self.policy,
            created_at=self.created_at,
            items=self.items + tuple(items),
            remote_artifacts_present=self.remote_artifacts_present,
            data_persistence=self.data_persistence,
            crate_version=self.crate_version,
            compss_version=self.compss_version,
        )


__all__ = [
    "ArtifactReference",
    "ArtifactVerificationResult",
    "VerificationIssue",
    "VerificationPolicy",
    "VerificationSeverity",
    "VerificationState",
    "VerificationSummary",
]