from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Protocol, runtime_checkable

from compss_rs.application.ports.file_system import (
    CopyRequest,
    DirectoryCreateRequest,
    FileSystemManager,
    FileSystemOperationResult,
)
from compss_rs.domain.errors import FileSystemError, ValidationError
from compss_rs.domain.models.crate import CrateSummary


class ConfigureNewDatasetStatus(str, Enum):
    PENDING = "pending"
    VALIDATED = "validated"
    PREPARED = "prepared"
    COPIED = "copied"
    FAILED = "failed"


@dataclass(frozen=True, slots=True)
class ConfigureNewDatasetRequest:
    crate: CrateSummary
    source_dataset_root: Path
    target_dataset_root: Path | None = None
    preserve_directory_structure: bool = True
    overwrite_existing: bool = False
    include_hidden_files: bool = True
    create_target_directory: bool = True

    def __post_init__(self) -> None:
        if self.crate is None:
            raise ValidationError("ConfigureNewDatasetRequest.crate cannot be None")
        if not str(self.source_dataset_root).strip():
            raise ValidationError("ConfigureNewDatasetRequest.source_dataset_root cannot be empty")


@dataclass(frozen=True, slots=True)
class ConfigureNewDatasetPlan:
    request: ConfigureNewDatasetRequest
    source_root: Path
    target_root: Path
    source_exists: bool = False
    target_exists: bool = False
    files_to_copy: tuple[Path, ...] = ()

    @property
    def total_files(self) -> int:
        return len(self.files_to_copy)


@dataclass(frozen=True, slots=True)
class ConfigureNewDatasetResult:
    status: ConfigureNewDatasetStatus
    request: ConfigureNewDatasetRequest
    plan: ConfigureNewDatasetPlan
    created_target_directory: bool = False
    copied_items: tuple[Path, ...] = ()
    operations: tuple[FileSystemOperationResult, ...] = ()
    warnings: tuple[str, ...] = ()
    notes: tuple[str, ...] = ()
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    @property
    def prepared(self) -> bool:
        return self.status in {ConfigureNewDatasetStatus.PREPARED, ConfigureNewDatasetStatus.COPIED}

    @property
    def copied(self) -> bool:
        return self.status == ConfigureNewDatasetStatus.COPIED

    @property
    def has_warnings(self) -> bool:
        return len(self.warnings) > 0

    @property
    def has_notes(self) -> bool:
        return len(self.notes) > 0


@runtime_checkable
class ConfigureNewDatasetUseCase(Protocol):
    def execute(self, request: ConfigureNewDatasetRequest) -> ConfigureNewDatasetResult:
        """
        Prepare a new dataset workspace from an existing source dataset.
        """
        ...


@runtime_checkable
class ConfigureNewDatasetPlanner(Protocol):
    def build_plan(self, request: ConfigureNewDatasetRequest) -> ConfigureNewDatasetPlan:
        """
        Build the dataset copy plan.
        """
        ...


class ConfigureNewDatasetPortError(FileSystemError):
    pass


class ConfigureNewDatasetFailure(ConfigureNewDatasetPortError):
    def __init__(self, message: str, details: str | None = None):
        super().__init__(message=message, details=details, recoverable=False)


class DefaultConfigureNewDatasetService:
    def __init__(self, file_system: FileSystemManager) -> None:
        self._file_system = file_system

    def build_plan(self, request: ConfigureNewDatasetRequest) -> ConfigureNewDatasetPlan:
        source_root = request.source_dataset_root
        target_root = request.target_dataset_root or request.crate.location.working_path or request.crate.location.original_path
        if target_root is None:
            raise ConfigureNewDatasetFailure(
                "Could not determine a target dataset root",
                details="crate location does not define a usable workspace path",
            )

        source_exists = self._file_system.exists(source_root)
        target_exists = self._file_system.exists(target_root)

        if not source_exists:
            raise ConfigureNewDatasetFailure(
                f"Source dataset does not exist: {source_root}",
            )

        files_to_copy = self._collect_paths(source_root, include_hidden=request.include_hidden_files)
        return ConfigureNewDatasetPlan(
            request=request,
            source_root=source_root,
            target_root=target_root,
            source_exists=source_exists,
            target_exists=target_exists,
            files_to_copy=tuple(files_to_copy),
        )

    def execute(self, request: ConfigureNewDatasetRequest) -> ConfigureNewDatasetResult:
        plan = self.build_plan(request)
        operations: list[FileSystemOperationResult] = []
        copied_items: list[Path] = []
        warnings: list[str] = []

        created_target_directory = False
        if request.create_target_directory and not self._file_system.exists(plan.target_root):
            directory_result = self._file_system.create_directory(
                DirectoryCreateRequest(path=plan.target_root, parents=True, exist_ok=True)
            )
            operations.append(directory_result)
            created_target_directory = directory_result.succeeded
            if not directory_result.succeeded:
                raise ConfigureNewDatasetFailure(
                    f"Could not create target dataset directory: {plan.target_root}",
                    details=directory_result.message,
                )

        target_dataset_root = plan.target_root
        if request.preserve_directory_structure:
            self._copy_tree(plan.source_root, target_dataset_root, operations, copied_items, request.overwrite_existing)
        else:
            warnings.append(
                "Directory structure preservation was disabled; the dataset was copied using a flat strategy"
            )
            self._copy_flat(plan.source_root, target_dataset_root, operations, copied_items, request.overwrite_existing)

        status = ConfigureNewDatasetStatus.COPIED if copied_items else ConfigureNewDatasetStatus.PREPARED

        return ConfigureNewDatasetResult(
            status=status,
            request=request,
            plan=plan,
            created_target_directory=created_target_directory,
            copied_items=tuple(copied_items),
            operations=tuple(operations),
            warnings=tuple(dict.fromkeys(warnings)),
        )

    def _collect_paths(self, root: Path, include_hidden: bool) -> list[Path]:
        paths: list[Path] = []
        stack: list[Path] = [root]

        while stack:
            current = stack.pop()
            if current.name.startswith(".") and not include_hidden:
                continue
            paths.append(current)
            if self._file_system.is_directory(current):
                for entry in self._file_system.list_directory(current):
                    stack.append(entry.path)

        return paths

    def _copy_tree(
        self,
        source_root: Path,
        target_root: Path,
        operations: list[FileSystemOperationResult],
        copied_items: list[Path],
        overwrite_existing: bool,
    ) -> None:
        for entry in self._file_system.list_directory(source_root):
            relative_name = entry.path.name
            destination = target_root / relative_name

            if entry.is_directory:
                directory_result = self._file_system.create_directory(
                    DirectoryCreateRequest(path=destination, parents=True, exist_ok=True)
                )
                operations.append(directory_result)
                copied_items.append(destination)
                if directory_result.succeeded:
                    self._copy_tree(entry.path, destination, operations, copied_items, overwrite_existing)
                continue

            copy_result = self._file_system.copy(
                CopyRequest(
                    source=entry.path,
                    destination=destination,
                    recursive=False,
                    overwrite=overwrite_existing,
                )
            )
            operations.append(copy_result)
            if copy_result.succeeded:
                copied_items.append(destination)

    def _copy_flat(
        self,
        source_root: Path,
        target_root: Path,
        operations: list[FileSystemOperationResult],
        copied_items: list[Path],
        overwrite_existing: bool,
    ) -> None:
        for entry in self._file_system.list_directory(source_root):
            destination = target_root / entry.path.name
            if entry.is_directory:
                directory_result = self._file_system.create_directory(
                    DirectoryCreateRequest(path=destination, parents=True, exist_ok=True)
                )
                operations.append(directory_result)
                copied_items.append(destination)
                continue

            copy_result = self._file_system.copy(
                CopyRequest(
                    source=entry.path,
                    destination=destination,
                    recursive=False,
                    overwrite=overwrite_existing,
                )
            )
            operations.append(copy_result)
            if copy_result.succeeded:
                copied_items.append(destination)


def has_copied_items(result: ConfigureNewDatasetResult) -> bool:
    return result.copied


def has_warnings(result: ConfigureNewDatasetResult) -> bool:
    return result.has_warnings


__all__ = [
    "ConfigureNewDatasetFailure",
    "ConfigureNewDatasetPlan",
    "ConfigureNewDatasetPortError",
    "ConfigureNewDatasetRequest",
    "ConfigureNewDatasetResult",
    "ConfigureNewDatasetStatus",
    "ConfigureNewDatasetUseCase",
    "DefaultConfigureNewDatasetService",
    "has_copied_items",
    "has_warnings",
]