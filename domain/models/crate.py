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

from rocrate.rocrate import ROCrate


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


class ArtifactKind(str, Enum):
    INPUT = "input"
    OUTPUT = "output"
    SOURCE = "source"
    RESOURCE = "resource"
    RESULT = "result"
    OTHER = "other"


@dataclass(frozen=True, slots=True)
class CrateSource:
    type: CrateSourceKind
    value: str
    rocrate: ROCrate | None = None

    def __post_init__(self) -> None:
        if not self.value.strip():
            raise ValueError("CrateSource.value cannot be empty")

    def with_rocrate(self, rocrate: ROCrate | None) -> "CrateSource":
        return replace(self, rocrate=rocrate)


@dataclass(frozen=True, slots=True)
class CrateLocation:
    original_path: Path
    crate_path: Path

    def __post_init__(self) -> None:
        if not str(self.original_path).strip():
            raise ValueError("CrateLocation.original_path cannot be empty")
        if not str(self.crate_path).strip():
            raise ValueError("CrateLocation.crate_path cannot be empty")


@dataclass(frozen=True, slots=True)
class WorkflowParticipant:
    name: str
    role: str = "participant"
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
    participant: WorkflowParticipant | None = None
    license: str | None = None
    crate_version: str | None = None
    compss_version: str | None = None
    data_persistence: DataPersistenceKind = DataPersistenceKind.UNKNOWN
    source_metadata_path: Path | None = None
    generated_at: datetime | None = None
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    execution_site: str | None = None
    rocrate: ROCrate | None = None

    def __post_init__(self) -> None:
        if not self.name.strip():
            raise ValueError("WorkflowMetadata.name cannot be empty")

    def with_participant(self, participant: WorkflowParticipant | None) -> "WorkflowMetadata":
        return replace(self, participant=participant)

    def with_rocrate(self, rocrate: ROCrate | None) -> "WorkflowMetadata":
        return replace(self, rocrate=rocrate)


@dataclass(frozen=True, slots=True)
class WorkflowArtifact:
    type: ArtifactKind
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
class CrateSummary:
    source: CrateSource
    location: CrateLocation
    metadata: WorkflowMetadata
    index: CrateIndex = field(default_factory=CrateIndex)
    crate_format_version: str | None = None
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    rocrate: ROCrate | None = None

    @property
    def has_inputs(self) -> bool:
        return len(self.index.inputs) > 0

    @property
    def has_outputs(self) -> bool:
        return len(self.index.outputs) > 0

    @property
    def all_artifacts(self) -> tuple[WorkflowArtifact, ...]:
        return self.index.all_artifacts()

    def with_rocrate(self, rocrate: ROCrate | None) -> "CrateSummary":
        return replace(self, rocrate=rocrate)