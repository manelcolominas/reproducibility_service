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

from dataclasses import dataclass, field, replace
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path

class CrateSourceKind(str, Enum):
    """
        Represents the kind of source from which a crate 
        can be imported. It can be a directory, a zip file, or a URL.
    """
    DIRECTORY = "directory"
    ZIP = "zip"
    URL = "url"


class DataPersistenceKind(str, Enum):
    TRUE = "true"
    FALSE = "false"
    UNKNOWN = "unknown"

@dataclass(frozen=True, slots=True)
class CrateSource:
    type: CrateSourceKind
    name: str

    def __post_init__(self) -> None:
        if not self.name.strip():
            raise ValueError("CrateSource.name cannot be empty")


@dataclass(frozen=True, slots=True)
class WorkflowParticipant:
    name: str
    role: str
    email: str | None = None
    organization_name: str | None = None
    orcid: str | None = None
    ror: str | None = None

    def __post_init__(self) -> None:
        if not self.role.strip():
            raise ValueError("WorkflowParticipant.role cannot be empty")


@dataclass(frozen=True, slots=True)
class WorkflowMetadata:
    name: str
    description: str = ""
    version: str | None = None
    authors: tuple[WorkflowParticipant, ...] = ()
    agent: WorkflowParticipant | None = None
    license: str | None = None
    crate_version: str | None = None
    compss_version: str | None = None
    data_persistence: DataPersistenceKind = DataPersistenceKind.UNKNOWN
    source_metadata_path: Path | None = None
    generated_at: datetime | None = None
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    execution_site: str | None = None

    def __post_init__(self) -> None:
        if not self.name.strip():
            raise ValueError("WorkflowMetadata.name cannot be empty")

    def with_agent(self, agent: WorkflowParticipant | None) -> "WorkflowMetadata":
        return replace(self, agent=agent)

class ArtifactKind(str, Enum):
    SOURCE = "source"
    INPUT = "input"
    OUTPUT = "output"

@dataclass(frozen=True, slots=True)
class WorkflowArtifact:
    type: ArtifactKind
    name: str
    path: str
    size_bytes: int | None = None
    accessible: bool = True
    exists: bool = True

    def __post_init__(self) -> None:
        if not self.name.strip():
            raise ValueError("WorkflowArtifact.name cannot be empty")
        if not self.path.strip():
            raise ValueError("WorkflowArtifact.path cannot be empty")
        if self.size_bytes is not None and self.size_bytes < 0:
            raise ValueError("WorkflowArtifact.size_bytes cannot be negative")

@dataclass(frozen=True, slots=True)
class WorkflowArtifactSummary:
    total: int = 0
    artifacts: list[WorkflowArtifact] = field(default_factory=list)
    def __post_init__(self) -> None:
        object.__setattr__(self, "total", len(self.artifacts))