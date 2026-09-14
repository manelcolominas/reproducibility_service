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
from datetime import datetime
from enum import Enum
from pathlib import Path

from dataclasses import dataclass
from pathlib import Path
from rocrate.rocrate import ROCrate

@dataclass(frozen=True, slots=True)
class SourceAcquisitionResult:
    """
    The SourceAcquisitionResult is an object whose main objective is to store how
    the crate source was obtained, whether it was downloaded, extracted, or was already on
    the disk.
    """

    source: CrateSource
    source_root: Path
    extracted: bool = False
    downloaded: bool = False

    @property
    def kind(self) -> str:
        if self.downloaded:
            return "downloaded"
        if self.extracted:
            return "extracted"
        return "already in disk"

    def __post_init__(self) -> None:
        # Validate that the source_root is not empty.
        if not str(self.source_root).strip():
            raise ValueError("SourceAcquisitionResult.source_root cannot be empty")
        # Validate that the source_root exists on the filesystem.
        if not self.source_root.exists():
            raise ValueError("SourceAcquisitionResult.source_root does not exist")


@dataclass(frozen=True, slots=True)
class SourceValidationResult:
    """
    A class made to store the result of validating a CrateSource. 
    It saves the attributes that indicate if the source exists, if
    it is readable, if it is a directory, if it is a file, if it is
    a URL, and a message describing the validation result.
    """
    source: CrateSource
    exists: bool
    readable: bool
    directory: bool
    file: bool
    url: bool
    message: str = ""

    @property
    def is_valid(self) -> bool:
        return self.exists and self.readable and (self.directory or self.file or self.url)

    def load_rocrate_if_valid(self, root: Path) -> ROCrate | None:
        try:
            crate = ROCrate(root)
            return crate
        except Exception:
            raise ValueError("Failed to load RO-Crate from the specified root")


class CrateSourceKind(str, Enum):
    """
        Represents the kind of source from which a crate 
        can be imported. It can be a directory, a zip file, or a URL.
    """
    DIRECTORY = "directory"
    ZIP = "zip"
    URL = "url"


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
        if not self.name.strip():
            raise ValueError("WorkflowParticipant.name cannot be empty")


@dataclass(frozen=True, slots=True)
class WorkflowMetadata:
    name: str
    description: str = ""
    version: str | None = None
    authors: tuple[WorkflowParticipant, ...] = ()
    agent: WorkflowParticipant | None = None
    workflow_entity_summary: WorkflowEntitySummary | None = None
    license: str | None = None
    crate_version: str | None = None
    compss_version: str | None = None
    source_metadata_path: Path | None = None
    generated_at: datetime | None = None
    execution_site: str | None = None

    def __post_init__(self) -> None:
        if not self.name.strip():
            raise ValueError("WorkflowMetadata.name cannot be empty")

    def with_agent(self, agent: WorkflowParticipant | None) -> "WorkflowMetadata":
        return replace(self, agent=agent)


class EntityKind(str, Enum):
    SOFTWARE_SOURCE_CODE = "Software Source Code"
    IMAGE_OBJECT = "Image Object"
    INPUT_OR_OUTPUT = "Input or Output"
    WORKERS_OUTPUT = "Workers Output"
    WORKERS_ERROR = "Workers Error"
    COMPSS_WORKFLOW_YAML_FILE = "COMPSs Workflow Information yaml file"
    WORKFLOW_CONFIGURATION_YAML_FILE = "Workflow Configuration yaml file"
    README = "README"
    UNKNOWN = "unknown"
    COMPSS_SUBMISSION_COMMAND_LINE_FILE = "compss_submission_command_line_file"


@dataclass(frozen=True, slots=True)
class WorkflowEntity:
    type: EntityKind
    name: str
    path: str
    size_bytes: int | None = None
    declared_size_bytes: int | None = None
    size_matches: bool | None = None
    exists: bool = True

    def __post_init__(self) -> None:
        if not self.name.strip():
            raise ValueError("WorkflowEntity.name cannot be empty")


@dataclass(frozen=True, slots=True)
class WorkflowEntitySummary:
    total: int = 0
    total_success: int = 0
    total_failed: int = 0
    total_warnings: int = 0
    entities: list[WorkflowEntity] = field(default_factory=list)

    def __post_init__(self) -> None:
        object.__setattr__(self, "total", len(self.entities))