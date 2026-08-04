from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Protocol, runtime_checkable

from compss_rs.application.ports.file_system import FileSystemReader
from compss_rs.domain.errors import FileSystemError, ValidationError
from compss_rs.domain.models.crate import CrateSummary, WorkflowArtifact
from compss_rs.domain.models.verification import (
    ArtifactReference,
    ArtifactVerificationResult,
    VerificationIssue,
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
    fail_fast: bool = False

    def __post_init__(self) -> None:
        if self.crate is None:
            raise ValidationError("VerifyInputsRequest.crate cannot be None")


@dataclass(frozen=True, slots=True)
class VerifyInputsPlan:
    request: VerifyInputsRequest
    artifacts: tuple[ArtifactReference, ...]
    base_path: Path


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


@runtime_checkable
class VerifyInputsPlanner(Protocol):
    def build_plan(self, request: VerifyInputsRequest) -> VerifyInputsPlan:
        ...


class VerifyInputsPortError(FileSystemError):
    pass


class VerifyInputsFailure(VerifyInputsPortError):
    pass


class DefaultVerifyInputsService:
    def __init__(self, file_system: FileSystemReader) -> None:
        self._file_system = file_system

    def build_plan(self, request: VerifyInputsRequest) -> VerifyInputsPlan:
        crate = request.crate
        base_path = crate.location.working_path
        artifacts: list[ArtifactReference] = []

        for artifact in crate.all_artifacts:
            artifacts.append(
                ArtifactReference(
                    metadata_name=artifact.name,
                    metadata_id=artifact.metadata_id or artifact.path,
                    expected_path=artifact.path,
                )
            )

        return VerifyInputsPlan(
            request=request,
            artifacts=tuple(artifacts),
            base_path=base_path,
        )

    def execute(self, request: VerifyInputsRequest) -> VerifyInputsResult:
        plan = self.build_plan(request)
        results: list[ArtifactVerificationResult] = []
        warnings: list[str] = []
        notes: list[str] = []

        for artifact in plan.artifacts:
            result = self._verify_artifact(artifact, plan.base_path)
            results.append(result)

            if result.has_issues:
                notes.extend(issue.message for issue in result.issues)
            if result.state == VerificationState.SIZE_MISMATCH:
                warnings.append(f"Size mismatch for {artifact.metadata_name}")

            if request.fail_fast and result.is_error:
                break

        summary = VerificationSummary(
            crate_path=plan.base_path,
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

    def _verify_artifact(
        self,
        artifact: ArtifactReference,
        base_path: Path,
    ) -> ArtifactVerificationResult:
        resolved_path = base_path / artifact.expected_path if artifact.expected_path else base_path / artifact.metadata_id

        if not self._file_system.exists(resolved_path):
            issue = VerificationIssue(
                code="missing",
                message=f"Artifact not found: {resolved_path}",
                severity=VerificationSeverity.ERROR,
            )
            return ArtifactVerificationResult(
                reference=artifact,
                state=VerificationState.MISSING,
                resolved_path=resolved_path,
                exists=False,
                accessible=False,
                issues=(issue,),
            )

        metadata = self._file_system.metadata(resolved_path)

        if not metadata.readable:
            issue = VerificationIssue(
                code="access-denied",
                message=f"Artifact is not readable: {resolved_path}",
                severity=VerificationSeverity.ERROR,
            )
            return ArtifactVerificationResult(
                reference=artifact,
                state=VerificationState.ACCESS_DENIED,
                resolved_path=resolved_path,
                exists=True,
                accessible=False,
                issues=(issue,),
            )

        return ArtifactVerificationResult(
            reference=artifact,
            state=VerificationState.VERIFIED,
            resolved_path=resolved_path,
            exists=True,
            accessible=True,
            size_actual=metadata.size_bytes,
        )