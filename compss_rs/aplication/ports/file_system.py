from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Protocol, runtime_checkable

from compss_rs.domain.errors import FileSystemError, ValidationError


@dataclass(frozen=True, slots=True)
class FileMetadata:
    path: Path
    exists: bool
    is_file: bool
    is_directory: bool
    size_bytes: int | None = None
    readable: bool = True
    writable: bool = True
    executable: bool = False

    def __post_init__(self) -> None:
        if not str(self.path).strip():
            raise ValidationError("FileMetadata.path cannot be empty")


@dataclass(frozen=True, slots=True)
class DirectoryListingEntry:
    path: Path
    name: str
    is_directory: bool
    is_file: bool
    size_bytes: int | None = None

    def __post_init__(self) -> None:
        if not self.name.strip():
            raise ValidationError("DirectoryListingEntry.name cannot be empty")


@dataclass(frozen=True, slots=True)
class CopyRequest:
    source: Path
    destination: Path
    recursive: bool = True
    overwrite: bool = False

    def __post_init__(self) -> None:
        if not str(self.source).strip():
            raise ValidationError("CopyRequest.source cannot be empty")
        if not str(self.destination).strip():
            raise ValidationError("CopyRequest.destination cannot be empty")


@dataclass(frozen=True, slots=True)
class MoveRequest:
    source: Path
    destination: Path
    overwrite: bool = False

    def __post_init__(self) -> None:
        if not str(self.source).strip():
            raise ValidationError("MoveRequest.source cannot be empty")
        if not str(self.destination).strip():
            raise ValidationError("MoveRequest.destination cannot be empty")


@dataclass(frozen=True, slots=True)
class DeleteRequest:
    path: Path
    recursive: bool = False
    missing_ok: bool = False

    def __post_init__(self) -> None:
        if not str(self.path).strip():
            raise ValidationError("DeleteRequest.path cannot be empty")


@dataclass(frozen=True, slots=True)
class WriteTextRequest:
    path: Path
    content: str
    encoding: str = "utf-8"
    create_parent: bool = True
    overwrite: bool = True

    def __post_init__(self) -> None:
        if not str(self.path).strip():
            raise ValidationError("WriteTextRequest.path cannot be empty")


@dataclass(frozen=True, slots=True)
class ReadTextRequest:
    path: Path
    encoding: str = "utf-8"

    def __post_init__(self) -> None:
        if not str(self.path).strip():
            raise ValidationError("ReadTextRequest.path cannot be empty")


@dataclass(frozen=True, slots=True)
class DirectoryCreateRequest:
    path: Path
    parents: bool = True
    exist_ok: bool = True

    def __post_init__(self) -> None:
        if not str(self.path).strip():
            raise ValidationError("DirectoryCreateRequest.path cannot be empty")


@dataclass(frozen=True, slots=True)
class FileSystemOperationResult:
    path: Path
    succeeded: bool
    message: str = ""
    bytes_transferred: int | None = None

    def __post_init__(self) -> None:
        if not str(self.path).strip():
            raise ValidationError("FileSystemOperationResult.path cannot be empty")


@runtime_checkable
class FileSystemReader(Protocol):
    def exists(self, path: Path) -> bool:
        ...

    def is_file(self, path: Path) -> bool:
        ...

    def is_directory(self, path: Path) -> bool:
        ...

    def metadata(self, path: Path) -> FileMetadata:
        ...

    def read_text(self, request: ReadTextRequest) -> str:
        ...

    def list_directory(self, path: Path) -> tuple[DirectoryListingEntry, ...]:
        ...


@runtime_checkable
class FileSystemWriter(Protocol):
    def create_directory(self, request: DirectoryCreateRequest) -> FileSystemOperationResult:
        ...

    def write_text(self, request: WriteTextRequest) -> FileSystemOperationResult:
        ...

    def copy(self, request: CopyRequest) -> FileSystemOperationResult:
        ...

    def move(self, request: MoveRequest) -> FileSystemOperationResult:
        ...

    def delete(self, request: DeleteRequest) -> FileSystemOperationResult:
        ...


@runtime_checkable
class FileSystemManager(FileSystemReader, FileSystemWriter, Protocol):
    def resolve(self, path: Path, strict: bool = False) -> Path:
        ...

    def relative_to(self, path: Path, base: Path) -> Path:
        ...

    def join(self, *parts: Path | str) -> Path:
        ...


class FileSystemPortError(FileSystemError):
    pass


class PathResolutionError(FileSystemPortError):
    def __init__(self, path: Path | str, details: str | None = None):
        super().__init__(
            message=f"Could not resolve path: {path}",
            details=details,
            recoverable=False,
        )


class MissingPathError(FileSystemPortError):
    def __init__(self, path: Path | str, details: str | None = None):
        super().__init__(
            message=f"Path does not exist: {path}",
            details=details,
            recoverable=False,
        )


class PermissionDeniedError(FileSystemPortError):
    def __init__(self, path: Path | str, details: str | None = None):
        super().__init__(
            message=f"Permission denied for path: {path}",
            details=details,
            recoverable=False,
        )


class CopyOperationError(FileSystemPortError):
    pass


class MoveOperationError(FileSystemPortError):
    pass


class DeleteOperationError(FileSystemPortError):
    pass


def is_directory_metadata(metadata: FileMetadata) -> bool:
    return metadata.is_directory


def is_file_metadata(metadata: FileMetadata) -> bool:
    return metadata.is_file


__all__ = [
    "CopyOperationError",
    "CopyRequest",
    "DeleteOperationError",
    "DeleteRequest",
    "DirectoryCreateRequest",
    "DirectoryListingEntry",
    "FileMetadata",
    "FileSystemManager",
    "FileSystemOperationResult",
    "FileSystemPortError",
    "FileSystemReader",
    "FileSystemWriter",
    "is_directory_metadata",
    "is_file_metadata",
    "MissingPathError",
    "MoveOperationError",
    "MoveRequest",
    "PathResolutionError",
    "PermissionDeniedError",
    "ReadTextRequest",
    "WriteTextRequest",
]