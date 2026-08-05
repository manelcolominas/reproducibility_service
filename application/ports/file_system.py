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
from pathlib import Path
from typing import Protocol, runtime_checkable

from domain.errors import FileSystemError


@dataclass(frozen=True, slots=True)
class FileMetadata:
    path: Path
    exists: bool
    is_file: bool
    is_directory: bool
    readable: bool = True
    writable: bool = True
    size_bytes: int | None = None

    def __post_init__(self) -> None:
        if not str(self.path).strip():
            raise ValueError("FileMetadata.path cannot be empty")


@dataclass(frozen=True, slots=True)
class DirectoryEntry:
    path: Path
    name: str
    is_file: bool
    is_directory: bool
    size_bytes: int | None = None

    def __post_init__(self) -> None:
        if not str(self.path).strip():
            raise ValueError("DirectoryEntry.path cannot be empty")
        if not self.name.strip():
            raise ValueError("DirectoryEntry.name cannot be empty")


@dataclass(frozen=True, slots=True)
class DirectoryCreateRequest:
    path: Path
    parents: bool = True
    exist_ok: bool = True


@dataclass(frozen=True, slots=True)
class CopyRequest:
    source: Path
    destination: Path
    recursive: bool = True
    overwrite: bool = False


@dataclass(frozen=True, slots=True)
class MoveRequest:
    source: Path
    destination: Path
    overwrite: bool = False


@dataclass(frozen=True, slots=True)
class DeleteRequest:
    path: Path
    recursive: bool = False
    missing_ok: bool = False


@dataclass(frozen=True, slots=True)
class FileSystemOperationResult:
    path: Path
    succeeded: bool
    message: str = ""
    bytes_transferred: int | None = None

    def __post_init__(self) -> None:
        if not str(self.path).strip():
            raise ValueError("FileSystemOperationResult.path cannot be empty")


@runtime_checkable
class FileSystemReader(Protocol):
    def exists(self, path: Path) -> bool:
        ...

    def metadata(self, path: Path) -> FileMetadata:
        ...

    def is_file(self, path: Path) -> bool:
        ...

    def is_directory(self, path: Path) -> bool:
        ...

    def read_text(self, path: Path, encoding: str = "utf-8") -> str:
        ...

    def list_directory(self, path: Path) -> tuple[DirectoryEntry, ...]:
        ...


@runtime_checkable
class FileSystemWriter(Protocol):
    def create_directory(self, request: DirectoryCreateRequest) -> FileSystemOperationResult:
        ...

    def copy(self, request: CopyRequest) -> FileSystemOperationResult:
        ...

    def move(self, request: MoveRequest) -> FileSystemOperationResult:
        ...

    def delete(self, request: DeleteRequest) -> FileSystemOperationResult:
        ...

    def write_text(self, path: Path, content: str, encoding: str = "utf-8") -> FileSystemOperationResult:
        ...


@runtime_checkable
class FileSystemManager(FileSystemReader, FileSystemWriter, Protocol):
    def join(self, *parts: Path | str) -> Path:
        ...

    def resolve(self, path: Path, strict: bool = False) -> Path:
        ...

    def relative_to(self, path: Path, base: Path) -> Path:
        ...


class FileSystemPortError(FileSystemError):
    pass


class PathResolutionError(FileSystemPortError):
    pass


class PermissionDeniedError(FileSystemPortError):
    pass


class MissingPathError(FileSystemPortError):
    pass