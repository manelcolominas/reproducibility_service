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
from enum import Enum
from pathlib import Path
from typing import Any, Mapping, Protocol, runtime_checkable

from domain.errors import MetadataError, ValidationError
from domain.models.crate import (
    CrateIndex,
    CrateSummary,
    DataPersistenceKind,
    WorkflowArtifact,
    WorkflowMetadata,
    WorkflowParticipant,
)


class MetadataFormat(str, Enum):
    UNKNOWN = "unknown"
    RO_CRATE_JSON = "ro_crate_json"
    COMPSS_YAML = "compss_yaml"


class MetadataSourceKind(str, Enum):
    FILE = "file"
    DIRECTORY = "directory"
    ARCHIVE = "archive"
    URL = "url"


@dataclass(frozen=True, slots=True)
class MetadataSource:
    type: MetadataSourceKind
    location: str
    format_hint: MetadataFormat = MetadataFormat.UNKNOWN

    def __post_init__(self) -> None:
        if not self.location.strip():
            raise ValidationError("MetadataSource.location cannot be empty")


@dataclass(frozen=True, slots=True)
class MetadataDocument:
    source: MetadataSource
    format: MetadataFormat
    raw: Mapping[str, Any]
    path: Path | None = None

    def __post_init__(self) -> None:
        if self.format == MetadataFormat.UNKNOWN:
            raise ValidationError("MetadataDocument.format cannot be UNKNOWN")


@dataclass(frozen=True, slots=True)
class MetadataNormalizationResult:
    document: MetadataDocument
    metadata: WorkflowMetadata | None = None
    index: CrateIndex | None = None
    crate: CrateSummary | None = None
    warnings: tuple[str, ...] = ()
    issues: tuple[str, ...] = ()

    @property
    def is_usable(self) -> bool:
        return self.metadata is not None or self.crate is not None


@dataclass(frozen=True, slots=True)
class MetadataParseRequest:
    source: MetadataSource
    expected_format: MetadataFormat = MetadataFormat.UNKNOWN
    allow_partial_metadata: bool = True
    strict: bool = False


@runtime_checkable
class MetadataParser(Protocol):
    def parse(self, request: MetadataParseRequest) -> MetadataDocument:
        ...


@runtime_checkable
class MetadataNormalizer(Protocol):
    def normalize(self, document: MetadataDocument) -> MetadataNormalizationResult:
        ...


@dataclass(frozen=True, slots=True)
class MetadataInspectionResult:
    ok: bool
    stdout: str | None = None
    stderr: str | None = None
    warning: str | None = None


@runtime_checkable
class MetadataInspector(Protocol):
    def inspect(self, document: MetadataDocument) -> MetadataInspectionResult:
        ...


class MetadataPortError(MetadataError):
    pass


class MetadataParseError(MetadataPortError):
    pass


class UnsupportedMetadataFormatError(MetadataPortError):
    pass


def build_workflow_metadata(
    name: str,
    description: str = "",
    version: str | None = None,
    authors: tuple[WorkflowParticipant, ...] = (),
    submitter: WorkflowParticipant | None = None,
    data_persistence: DataPersistenceKind = DataPersistenceKind.UNKNOWN,
    source_metadata_path: Path | None = None,
) -> WorkflowMetadata:
    return WorkflowMetadata(
        name=name,
        description=description,
        version=version,
        authors=authors,
        submitter=submitter,
        data_persistence=data_persistence,
        source_metadata_path=source_metadata_path,
    )