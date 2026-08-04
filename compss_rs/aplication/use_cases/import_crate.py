from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Protocol, runtime_checkable

from ports.crate_source import (
    CrateSourceAcquirer,
    CrateSourceInspector,
    CrateSourceResolver,
    CrateSourceValidator,
    SourceAcquisitionResult,
    SourceValidationResult,
)
from ports.file_system import FileSystemManager
from ports.metadata_parser import MetadataDocument, MetadataParser
from compss_rs.domain.errors import FileSystemError, MetadataError, ValidationError
from compss_rs.domain.models.crate import CrateLocation, CrateSource, CrateSummary
from compss_rs.domain.models.execution import ExecutionContext
from compss_rs.domain.models.verification import VerificationSummary


class ImportCrateStatus(str, Enum):
    PENDING = "pending"
    RESOLVED = "resolved"
    VALIDATED = "validated"
    PREPARED = "prepared"
    IMPORTED = "imported"
    FAILED = "failed"


@dataclass(frozen=True, slots=True)
class ImportCrateRequest:
    raw_source: str
    run_directory: Path
    allow_download: bool = True
    allow_archive_extraction: bool = True
    create_run_workspace: bool = True
    preserve_source: bool = True
    create_log_directory: bool = True
    create_results_directory: bool = True

    def __post_init__(self) -> None:
        if not self.raw_source.strip():
            raise ValidationError("ImportCrateRequest.raw_source cannot be empty")
        if not str(self.run_directory).strip():
            raise ValidationError("ImportCrateRequest.run_directory cannot be empty")


@dataclass(frozen=True, slots=True)
class ImportCrateResult:
    status: ImportCrateStatus
    source: CrateSource
    source_validation: SourceValidationResult
    acquisition: SourceAcquisitionResult | None
    location: CrateLocation
    summary: CrateSummary | None = None
    metadata_document: MetadataDocument | None = None
    verification: VerificationSummary | None = None
    context: ExecutionContext | None = None
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    warnings: tuple[str, ...] = ()
    notes: tuple[str, ...] = ()

    @property
    def imported(self) -> bool:
        return self.status == ImportCrateStatus.IMPORTED

    @property
    def has_warnings(self) -> bool:
        return len(self.warnings) > 0

    @property
    def has_notes(self) -> bool:
        return len(self.notes) > 0


@dataclass(frozen=True, slots=True)
class ImportCratePlan:
    request: ImportCrateRequest
    source: CrateSource
    destination_root: Path
    workspace_root: Path
    log_directory: Path
    results_directory: Path
    preserve_source: bool = True
    create_log_directory: bool = True
    create_results_directory: bool = True

    def __post_init__(self) -> None:
        for field_name in ("destination_root", "workspace_root", "log_directory", "results_directory"):
            if not str(getattr(self, field_name)).strip():
                raise ValidationError(f"ImportCratePlan.{field_name} cannot be empty")


@runtime_checkable
class ImportCrateUseCase(Protocol):
    def execute(self, request: ImportCrateRequest) -> ImportCrateResult:
        """
        Import a crate source into a prepared workspace and return the canonical result.
        """
        ...


@runtime_checkable
class ImportCratePlanner(Protocol):
    def build_plan(self, request: ImportCrateRequest, source: CrateSource) -> ImportCratePlan:
        """
        Build the filesystem layout and workspace plan for crate import.
        """
        ...


@runtime_checkable
class ImportCrateOrchestrator(Protocol):
    def resolve_source(self, raw_source: str) -> CrateSource:
        ...

    def validate_source(self, source: CrateSource) -> SourceValidationResult:
        ...

    def acquire_source(self, source: CrateSource, destination_root: Path) -> SourceAcquisitionResult:
        ...

    def inspect_metadata(self, prepared_root: Path) -> MetadataDocument:
        ...

    def prepare_context(self, plan: ImportCratePlan) -> ExecutionContext:
        ...


class ImportCratePortError(FileSystemError):
    pass


class ImportCrateMetadataError(MetadataError):
    pass


class ImportCrateFailure(ImportCratePortError):
    def __init__(self, message: str, details: str | None = None):
        super().__init__(message=message, details=details, recoverable=False)


def is_imported(result: ImportCrateResult) -> bool:
    return result.status == ImportCrateStatus.IMPORTED


def has_metadata(result: ImportCrateResult) -> bool:
    return result.metadata_document is not None


def has_verification(result: ImportCrateResult) -> bool:
    return result.verification is not None


__all__ = [
    "ImportCrateFailure",
    "ImportCrateMetadataError",
    "ImportCrateOrchestrator",
    "ImportCratePlan",
    "ImportCratePlanner",
    "ImportCrateRequest",
    "ImportCrateResult",
    "ImportCrateStatus",
    "ImportCrateUseCase",
    "has_metadata",
    "has_verification",
    "is_imported",
]