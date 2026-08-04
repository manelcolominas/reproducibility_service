from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Protocol, runtime_checkable

from compss_rs.application.ports.crate_source import (
    CrateSourceAcquirer,
    CrateSourceResolver,
    CrateSourceValidator,
    SourceAcquisitionResult,
    SourceValidationResult,
)
from compss_rs.application.ports.file_system import (
    DirectoryCreateRequest,
    FileSystemManager,
)
from compss_rs.domain.errors import FileSystemError, ValidationError
from compss_rs.domain.models.crate import CrateLocation, CrateSource, CrateSummary


class ImportCrateStatus(str, Enum):
    PENDING = "pending"
    VALIDATED = "validated"
    PREPARED = "prepared"
    IMPORTED = "imported"
    FAILED = "failed"


@dataclass(frozen=True, slots=True)
class ImportCrateRequest:
    raw_source: str
    run_directory: Path
    create_workspace: bool = True

    def __post_init__(self) -> None:
        if not self.raw_source.strip():
            raise ValidationError("ImportCrateRequest.raw_source cannot be empty")
        if not str(self.run_directory).strip():
            raise ValidationError("ImportCrateRequest.run_directory cannot be empty")


@dataclass(frozen=True, slots=True)
class ImportCratePlan:
    request: ImportCrateRequest
    source: CrateSource
    validation: SourceValidationResult
    workspace_root: Path
    crate_root: Path
    log_dir: Path
    results_dir: Path

    def __post_init__(self) -> None:
        for path_name in ("workspace_root", "crate_root", "log_dir", "results_dir"):
            if not str(getattr(self, path_name)).strip():
                raise ValidationError(f"ImportCratePlan.{path_name} cannot be empty")


@dataclass(frozen=True, slots=True)
class ImportCrateResult:
    status: ImportCrateStatus
    request: ImportCrateRequest
    source: CrateSource
    validation: SourceValidationResult
    acquisition: SourceAcquisitionResult | None
    location: CrateLocation
    crate: CrateSummary | None = None
    warnings: tuple[str, ...] = ()
    notes: tuple[str, ...] = ()
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    @property
    def imported(self) -> bool:
        return self.status == ImportCrateStatus.IMPORTED

    @property
    def has_warnings(self) -> bool:
        return len(self.warnings) > 0


@runtime_checkable
class ImportCrateUseCase(Protocol):
    def execute(self, request: ImportCrateRequest) -> ImportCrateResult:
        ...


@runtime_checkable
class ImportCratePlanner(Protocol):
    def build_plan(self, request: ImportCrateRequest) -> ImportCratePlan:
        ...


class ImportCratePortError(FileSystemError):
    pass


class ImportCrateFailure(ImportCratePortError):
    pass


class DefaultImportCrateService:
    def __init__(
        self,
        resolver: CrateSourceResolver,
        validator: CrateSourceValidator,
        acquirer: CrateSourceAcquirer,
        file_system: FileSystemManager,
    ) -> None:
        self._resolver = resolver
        self._validator = validator
        self._acquirer = acquirer
        self._file_system = file_system

    def build_plan(self, request: ImportCrateRequest) -> ImportCratePlan:
        source = self._resolver.resolve(request.raw_source)
        validation = self._validator.validate(source)

        workspace_root = request.run_directory
        crate_root = workspace_root / "crate"
        log_dir = workspace_root / "log"
        results_dir = workspace_root / "Results"

        return ImportCratePlan(
            request=request,
            source=source,
            validation=validation,
            workspace_root=workspace_root,
            crate_root=crate_root,
            log_dir=log_dir,
            results_dir=results_dir,
        )

    def execute(self, request: ImportCrateRequest) -> ImportCrateResult:
        plan = self.build_plan(request)

        if not plan.validation.is_valid:
            raise ImportCrateFailure(
                "Source validation failed",
                details=plan.validation.message or "the source is not usable",
            )

        if request.create_workspace:
            self._file_system.create_directory(
                DirectoryCreateRequest(path=plan.workspace_root, parents=True, exist_ok=True)
            )
            self._file_system.create_directory(
                DirectoryCreateRequest(path=plan.crate_root, parents=True, exist_ok=True)
            )
            self._file_system.create_directory(
                DirectoryCreateRequest(path=plan.log_dir, parents=True, exist_ok=True)
            )
            self._file_system.create_directory(
                DirectoryCreateRequest(path=plan.results_dir, parents=True, exist_ok=True)
            )

        acquisition = self._acquirer.acquire(plan.source, plan.crate_root)
        location = CrateLocation(
            original_path=acquisition.source_root,
            working_path=acquisition.prepared_root,
        )

        return ImportCrateResult(
            status=ImportCrateStatus.IMPORTED,
            request=request,
            source=plan.source,
            validation=plan.validation,
            acquisition=acquisition,
            location=location,
            notes=("Crate source prepared successfully",),
        )