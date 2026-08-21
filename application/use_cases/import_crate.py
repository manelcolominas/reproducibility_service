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

from application.ports.crate_source import (
    CrateSourceAcquirer,
    CrateSourceResolver,
    CrateSourceValidator,
    SourceAcquisitionResult,
    SourceValidationResult,
)
from application.ports.file_system import (
    DirectoryCreateRequest,
    #FileSystemManager,
)
from domain.errors import FileSystemError, ValidationError
from domain.models.crate import CrateLocation, CrateSource, CrateSummary
from infrastructure.adapters import LocalFileSystem


class ImportCrateStatus(str, Enum):
    PENDING = "pending"
    VALIDATED = "validated"
    PREPARED = "prepared"
    IMPORTED = "imported"
    FAILED = "failed"


@dataclass(frozen=True, slots=True)
class ImportCrateRequest:
    raw_source: str
    workspace_directory: Path
    create_workspace: bool = True
    crate_directory: Path | None = None
    reuse_existing_crate: bool = True


    def __post_init__(self) -> None:
        if not self.raw_source.strip():
            raise ValidationError("ImportCrateRequest.raw_source cannot be empty")
        if not str(self.workspace_directory).strip():
            raise ValidationError("ImportCrateRequest.workspace_directory cannot be empty")
        if self.crate_directory is not None and not str(self.crate_directory).strip():
            raise ValidationError("ImportCrateRequest.crate_directory cannot be empty")


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
        #file_system: FileSystemManager,
        file_system: LocalFileSystem,
        original_crate_dir_name: str,
        log_dir_name: str,
        results_dir_name: str,
    ) -> None:
        self._resolver = resolver
        self._validator = validator
        self._acquirer = acquirer
        self._file_system = file_system
        self._original_crate_dir_name = original_crate_dir_name
        self._log_dir_name = log_dir_name
        self._results_dir_name = results_dir_name

    def build_plan(self, request: ImportCrateRequest) -> ImportCratePlan:
        source = self._resolver.resolve(request.raw_source)
        validation = self._validator.validate(source)

        workspace_root = request.workspace_directory
        crate_name = self._original_crate_dir_name.strip()
        crate_root = request.crate_directory or (
            workspace_root if not crate_name else workspace_root / crate_name
        )
        log_dir = workspace_root / self._log_dir_name
        results_dir = workspace_root / self._results_dir_name

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

        reused = request.reuse_existing_crate and self._looks_like_crate(plan.crate_root)

        if reused:
            acquisition = SourceAcquisitionResult(
            source=plan.source,
            source_root=plan.crate_root,
            prepared_root=plan.crate_root,
            )
            notes = ("Existing crate reused",)
        else:
            acquisition = self._acquirer.acquire(plan.source, plan.crate_root)
            notes = ("Crate source prepared successfully",)

        location = CrateLocation(
        original_path=acquisition.source_root,
        copied_downloaded_crate_path=acquisition.prepared_root,
        )

        return ImportCrateResult(
            status=ImportCrateStatus.IMPORTED,
            request=request,
            source=plan.source,
            validation=plan.validation,
            acquisition=acquisition,
            location=location,
            notes=notes,
            )

    def _looks_like_crate(self, crate_root: Path) -> bool:
        if not crate_root.exists():
            return False
        if (crate_root / "ro-crate-metadata.json").is_file():
            return True
        if (crate_root / "ro-crate-info.yaml").is_file():
            return True
        return any(crate_root.rglob("ro-crate-metadata.json")) or any(crate_root.rglob("ro-crate-info.yaml"))