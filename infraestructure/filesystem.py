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

@dataclass(frozen=True, slots=True)
class FileSystemOperationResult:
    """
    Represents the result of a file system operation.

    Attributes:
        path (Path): The path on which the operation was performed.
        succeeded (bool): Whether the operation succeeded.
        message (str): An optional message providing additional information.
        bytes_transferred (int | None): The number of bytes transferred, if applicable.
    """
    path: Path
    succeeded: bool
    message: str = ""
    bytes_transferred: int | None = None

    def __post_init__(self) -> None:
        if not str(self.path).strip():
            raise ValueError("FileSystemOperationResult.path cannot be empty")


class LocalFileSystem:
    """
        The LocalFileSystem class provides an interface for managing files and directories
        on the local filesystem. It uses Python's pathlib, shutil, and os modules to perform
        common filesystem operations, such as checking whether a file or directory exists,
        writing files, creating directories, files
        and directories. It also provides methods for retrieving file metadata and manipulating
        paths. The class acts as an abstraction layer, allowing the rest of the application to
        interact with the local filesystem without directly depending on the underlying filesystem
        operations.
    """

    # verify if a path exists
    def exists(self, path: Path) -> bool:
        return Path(path).exists()
    
    def create_directory(self, path: Path, parents: bool, exist_ok: bool) -> FileSystemOperationResult:
        """
        Creates a directory at the specified path.

        Parameters:
            path (Path): The path of the directory to create.
            parents (bool): Whether to create parent directories if they do not exist.
            exist_ok (bool): Whether to ignore the error if the directory already exists.

        Returns:
            FileSystemOperationResult: The status of the directory creation operation.
            
            class FileSystemOperationResult:
                path: Path The path on which the operation was performed.
                succeeded: bool Whether the operation succeeded.
                message: str = "" An optional message providing additional information about the operation.
                bytes_transferred: int | None = None The number of bytes transferred during the operation, if applicable.
        """
        try:
            Path(path).mkdir(parents=parents, exist_ok=exist_ok)
            return FileSystemOperationResult(path=path, succeeded=True)
        except OSError as exc:
            return FileSystemOperationResult(path=path, succeeded=False, message=str(exc))

    def write_text(self, path: Path, content: str, encoding: str = "utf-8") -> FileSystemOperationResult:
        path = Path(path)
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(content, encoding=encoding)
            return FileSystemOperationResult(path=path, succeeded=True, bytes_transferred=len(content))
        except OSError as exc:
            return FileSystemOperationResult(path=path, succeeded=False, message=str(exc))

    def get_size(self, path: Path) -> int:
        size_in_bytes = path.stat().st_size
        return size_in_bytes