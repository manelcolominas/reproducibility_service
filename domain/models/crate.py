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
    DIRECTORY = "directory"
    ZIP = "zip"
    URL = "url"


class DataPersistenceKind(str, Enum):
    TRUE = "true"
    FALSE = "false"
    UNKNOWN = "unknown"


class ArtifactKind(str, Enum):
    INPUT = "input"
    OUTPUT = "output"
    SOURCE = "source"
    RESOURCE = "resource"
    RESULT = "result"
    OTHER = "other"


@dataclass(frozen=True, slots=True)
class CrateSource:
    kind: CrateSourceKind
    value: str

    def __post_init__(self) -> None:
        if not self.value.strip():
            raise ValueError("CrateSource.value cannot be empty")


@dataclass(frozen=True, slots=True)
class CrateLocation:
    original_path: Path
    working_path: Path

    def __post_init__(self) -> None:
        if not str(self.original_path).strip():
            raise ValueError("CrateLocation.original_path cannot be empty")
        if not str(self.working_path).strip():
            raise ValueError("CrateLocation.working_path cannot be empty")


@dataclass(frozen=True, slots=True)
class WorkflowParticipant:
    name: str
    role: str = "agent"
    email: str | None = None
    organization_name: str | None = None
    orcid: str | None = None
    ror: str | None = None

    def __post_init__(self) -> None:
        if not self.name.strip():
            raise ValueError("WorkflowParticipant.name cannot be empty")
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

    def __post_init__(self) -> None:
        if not self.name.strip():
            raise ValueError("WorkflowMetadata.name cannot be empty")

    def with_agent(self, agent: WorkflowParticipant | None) -> WorkflowMetadata:
        return replace(self, agent=agent)


@dataclass(frozen=True, slots=True)
class WorkflowArtifact:
    kind: ArtifactKind
    name: str
    path: str
    metadata_id: str | None = None
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
class CrateIndex:
    inputs: tuple[WorkflowArtifact, ...] = ()
    outputs: tuple[WorkflowArtifact, ...] = ()
    sources: tuple[WorkflowArtifact, ...] = ()
    resources: tuple[WorkflowArtifact, ...] = ()

    def all_artifacts(self) -> tuple[WorkflowArtifact, ...]:
        return (*self.inputs, *self.outputs, *self.sources, *self.resources)


@dataclass(frozen=True, slots=True)
class WorkflowCommand:
    executable: str
    arguments: tuple[str, ...] = ()
    working_directory: Path | None = None

    def __post_init__(self) -> None:
        if not self.executable.strip():
            raise ValueError("WorkflowCommand.executable cannot be empty")

    def as_list(self) -> list[str]:
        return [self.executable, *self.arguments]

    def as_string(self) -> str:
        return " ".join(self.as_list())


@dataclass(frozen=True, slots=True)
class CrateSummary:
    source: CrateSource
    location: CrateLocation
    metadata: WorkflowMetadata
    index: CrateIndex = field(default_factory=CrateIndex)
    crate_format_version: str | None = None
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    @property
    def has_inputs(self) -> bool:
        return len(self.index.inputs) > 0

    @property
    def has_outputs(self) -> bool:
        return len(self.index.outputs) > 0

    @property
    def all_artifacts(self) -> tuple[WorkflowArtifact, ...]:
        return self.index.all_artifacts()