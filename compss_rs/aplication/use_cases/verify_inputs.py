from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Protocol, runtime_checkable

from compss_rs.application.ports.file_system import FileMetadata, FileSystemReader
from compss_rs.domain.errors import FileSystemError, ValidationError
from compss_rs.domain.models.crate import CrateSummary, DataPersistenceKind, WorkflowArtifact
from compss_rs.domain.models.verification import (
    ArtifactReference,
    ArtifactVerificationResult,
    VerificationIssue,
    VerificationPolicy,
    VerificationSeverity,
    VerificationState,
    VerificationSummary,
)


class VerifyInputsStatus(str, Enum):
    PENDING = "pending"
    CHECKING = "checking"
    VERIFIED = "verified"
    WARNING = "warning"
    FAILED = "failed"


@dataclass(frozen=True, slots=True)
class VerifyInputsRequest:
    crate: CrateSummary
    verification_policy: VerificationPolicy = field(default_factory=VerificationPolicy)
    base_path: Path | None = None
    include_sources: bool = True
    include_outputs: bool = True
    include_remote_resources: bool = True
    fail_fast: bool = False

    def __post_init__(self) -> None:
        if self.crate is None:
            raise ValidationError("VerifyInputsRequest.crate cannot be None")


@dataclass(frozen=True, slots=True)
class VerifyInputsPlan:
    request: VerifyInputsRequest
    artifacts: tuple[ArtifactReference, ...]
    expected_root: Path | None = None
    data_persistence: DataPersistenceKind = DataPersistenceKind.UNKNOWN

    @property
    def total_artifacts(self) -> int:
        return len(self.artifacts)


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

    @property
    def has_notes(self) -> bool:
        return len(self.notes) > 0


@runtime_checkable
class VerifyInputsUseCase(Protocol):
    def execute(self, request: VerifyInputsRequest) -> VerifyInputsResult:
        """
        Verify the crate's declared artifacts against the available filesystem state.
        """
        ...


@runtime_checkable
class VerifyInputsPlanner(Protocol):
    def build_plan(self, request: VerifyInputsRequest) -> VerifyInputsPlan:
        """
        Build the verification plan for the crate artifacts.
        """
        ...


@runtime_checkable
class ArtifactVerifier(Protocol):
    def verify(self, artifact: ArtifactReference, base_path: Path | None) -> ArtifactVerificationResult:
        """
        Verify a single artifact.
        """
        ...


class VerifyInputsPortError(FileSystemError):
    pass


class VerifyInputsFailure(VerifyInputsPortError):
    def __init__(self, message: str, details: str | None = None):
        super().__init__(message=message, details=details, recoverable=False)


class DefaultVerifyInputsService:
    def __init__(self, file_system: FileSystemReader) -> None:
        self._file_system = file_system

    def build_plan(self, request: VerifyInputsRequest) -> VerifyInputsPlan:
        artifacts: list[ArtifactReference] = []
        crate = request.crate

        if request.include_sources:
            artifacts.extend(self._to_references(crate.index.sources))
        if request.include_outputs:
            artifacts.extend(self._to_references(crate.index.outputs))
        if request.include_remote_resources:
            artifacts.extend(self._to_references(crate.index.remote_resources))
        artifacts.extend(self._to_references(crate.index.inputs))

        seen: dict[tuple[str, str], ArtifactReference] = {}
        for artifact in artifacts:
            seen[(artifact.metadata_name, artifact.metadata_id)] = artifact

        expected_root = crate.location.working_path or crate.location.original_path
        return VerifyInputsPlan(
            request=request,
            artifacts=tuple(seen.values()),
            expected_root=expected_root,
            data_persistence=crate.metadata.data_persistence,
        )

    def execute(self, request: VerifyInputsRequest) -> VerifyInputsResult:
        plan = self.build_plan(request)

        items: list[ArtifactVerificationResult] = []
        warnings: list[str] = []
        notes: list[str] = []

        for artifact in plan.artifacts:
            result = self._verify_artifact(artifact, plan.expected_root)
            items.append(result)

            if result.is_warning:
                warnings.extend(issue.message for issue in result.issues if issue.severity == VerificationSeverity.WARNING)
            if result.has_issues:
                notes.extend(issue.message for issue in result.issues)

            if request.fail_fast and result.is_error:
                break

        summary = VerificationSummary(
            crate_path=request.crate.location.working_path or request.crate.location.original_path or Path("."),
            policy=request.verification_policy,
            items=tuple(items),
            remote_artifacts_present=request.crate.has_remote_resources,
            data_persistence=request.crate.metadata.data_persistence != DataPersistenceKind.FALSE,
            crate_version=request.crate.crate_format_version,
            compss_version=request.crate.metadata.compss_version,
        )

        if summary.has_failures:
            status = VerifyInputsStatus.FAILED
        elif summary.has_warnings:
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

    def _to_references(self, artifacts: tuple[WorkflowArtifact, ...]) -> list[ArtifactReference]:
        references: list[ArtifactReference] = []
        for artifact in artifacts:
            references.append(
                ArtifactReference(
                    metadata_name=artifact.name,
                    metadata_id=artifact.metadata_id or artifact.path.relative_path,
                    expected_relative_path=artifact.path.relative_path,
                    source_kind=artifact.kind.value,
                )
            )
        return references

    def _verify_artifact(
        self,
        artifact: ArtifactReference,
        base_path: Path | None,
    ) -> ArtifactVerificationResult:
        resolved_path = self._resolve_artifact_path(artifact, base_path)
        issues: list[VerificationIssue] = []

        if resolved_path is None:
            issues.append(
                VerificationIssue(
                    code="artifact-path-unresolved",
                    message=f"Could not resolve artifact path for {artifact.metadata_name}",
                    severity=VerificationSeverity.ERROR,
                )
            )
            return ArtifactVerificationResult(
                reference=artifact,
                state=VerificationState.MISSING,
                resolved_path=None,
                exists=False,
                accessible=False,
                issues=tuple(issues),
            )

        try:
            metadata = self._file_system.metadata(resolved_path)
        except Exception as exc:
            issues.append(
                VerificationIssue(
                    code="filesystem-error",
                    message=f"Could not read file metadata for {resolved_path}",
                    severity=VerificationSeverity.ERROR,
                    details=str(exc),
                )
            )
            return ArtifactVerificationResult(
                reference=artifact,
                state=VerificationState.ERROR,
                resolved_path=resolved_path,
                exists=False,
                accessible=False,
                issues=tuple(issues),
            )

        if not metadata.exists:
            issues.append(
                VerificationIssue(
                    code="missing",
                    message=f"Artifact not found: {resolved_path}",
                    severity=VerificationSeverity.ERROR,
                )
            )
            return ArtifactVerificationResult(
                reference=artifact,
                state=VerificationState.MISSING,
                resolved_path=resolved_path,
                exists=False,
                accessible=False,
                issues=tuple(issues),
            )

        if not metadata.readable:
            issues.append(
                VerificationIssue(
                    code="access-denied",
                    message=f"Artifact is not readable: {resolved_path}",
                    severity=VerificationSeverity.ERROR,
                )
            )
            return ArtifactVerificationResult(
                reference=artifact,
                state=VerificationState.ACCESS_DENIED,
                resolved_path=resolved_path,
                exists=True,
                accessible=False,
                issues=tuple(issues),
            )

        state = VerificationState.VERIFIED
        exists = True
        accessible = True
        size_expected = None
        size_actual = metadata.size_bytes

        if metadata.is_file and size_actual is None:
            issues.append(
                VerificationIssue(
                    code="size-unknown",
                    message=f"File size is unavailable for {resolved_path}",
                    severity=VerificationSeverity.WARNING,
                )
            )

        return ArtifactVerificationResult(
            reference=artifact,
            state=state,
            resolved_path=resolved_path,
            exists=exists,
            accessible=accessible,
            size_expected=size_expected,
            size_actual=size_actual,
            issues=tuple(issues),
        )

    def _resolve_artifact_path(self, artifact: ArtifactReference, base_path: Path | None) -> Path | None:
        if artifact.expected_relative_path:
            if base_path is not None:
                return base_path / artifact.expected_relative_path
            return Path(artifact.expected_relative_path)

        if base_path is not None:
            return base_path / artifact.metadata_id

        if artifact.metadata_id.startswith("/"):
            return Path(artifact.metadata_id)

        return None


def has_failures(result: VerifyInputsResult) -> bool:
    return result.summary.has_failures


def has_warnings(result: VerifyInputsResult) -> bool:
    return result.summary.has_warnings


def is_verified(result: VerifyInputsResult) -> bool:
    return result.verified


__all__ = [
    "ArtifactVerifier",
    "DefaultVerifyInputsService",
    "VerifyInputsFailure",
    "VerifyInputsPlan",
    "VerifyInputsPortError",
    "VerifyInputsRequest",
    "VerifyInputsResult",
    "VerifyInputsStatus",
    "VerifyInputsUseCase",
    "has_failures",
    "has_warnings",
    "is_verified",
]