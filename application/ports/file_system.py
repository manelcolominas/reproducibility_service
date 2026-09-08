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
