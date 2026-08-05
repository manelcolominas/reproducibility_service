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
    FileSystemManager,
)
from domain.errors import FileSystemError, ValidationError
from domain.models.crate import CrateLocation, CrateSource, CrateSummary


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
        workflow_dir_name: str,
        log_dir_name: str,
        results_dir_name: str,
    ) -> None:
        self._resolver = resolver
        self._validator = validator
        self._acquirer = acquirer
        self._file_system = file_system
        self._workflow_dir_name = workflow_dir_name
        self._log_dir_name = log_dir_name
        self._results_dir_name = results_dir_name

    def build_plan(self, request: ImportCrateRequest) -> ImportCratePlan:
        source = self._resolver.resolve(request.raw_source)
        validation = self._validator.validate(source)

        workspace_root = request.run_directory
        crate_root = workspace_root / self._workflow_dir_name
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