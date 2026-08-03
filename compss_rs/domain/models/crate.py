from __future__ import annotations

from dataclasses import dataclass, field, replace
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Iterable, Mapping, Sequence


class CrateSourceKind(str, Enum):
    LOCAL_DIRECTORY = "local_directory"
    ZIP_ARCHIVE = "zip_archive"
    URL = "url"
    REMOTE_PROVIDER = "remote_provider"


class DataPersistenceKind(str, Enum):
    TRUE = "true"
    FALSE = "false"
    UNKNOWN = "unknown"


class ArtifactKind(str, Enum):
    INPUT = "input"
    OUTPUT = "output"
    SOURCE = "source"
    RESOURCE = "resource"
    REMOTE = "remote"
    RESULT = "result"
    OTHER = "other"


@dataclass(frozen=True, slots=True)
class CrateSource:
    kind: CrateSourceKind
    value: str
    display_name: str | None = None

    def __post_init__(self) -> None:
        if not self.value.strip():
            raise ValueError("CrateSource.value cannot be empty")

    @property
    def is_remote(self) -> bool:
        return self.kind in {CrateSourceKind.URL, CrateSourceKind.REMOTE_PROVIDER}


@dataclass(frozen=True, slots=True)
class CrateLocation:
    source: CrateSource
    original_path: Path | None = None
    working_path: Path | None = None
    run_path: Path | None = None

    def __post_init__(self) -> None:
        if self.original_path is None and self.working_path is None and self.run_path is None:
            raise ValueError("CrateLocation must contain at least one path")

    def with_working_path(self, path: Path) -> CrateLocation:
        return replace(self, working_path=path)

    def with_run_path(self, path: Path) -> CrateLocation:
        return replace(self, run_path=path)


@dataclass(frozen=True, slots=True)
class ArtifactPath:
    relative_path: str
    resolved_path: Path | None = None
    exists: bool = False
    accessible: bool = True

    def __post_init__(self) -> None:
        if not self.relative_path.strip():
            raise ValueError("ArtifactPath.relative_path cannot be empty")


@dataclass(frozen=True, slots=True)
class WorkflowCommand:
    executable: str
    arguments: tuple[str, ...] = ()
    working_directory: Path | None = None
    environment: Mapping[str, str] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.executable.strip():
            raise ValueError("WorkflowCommand.executable cannot be empty")
        if not all(argument is not None for argument in self.arguments):
            raise ValueError("WorkflowCommand.arguments cannot contain None")

    def as_list(self) -> list[str]:
        return [self.executable, *self.arguments]

    def with_argument(self, argument: str) -> WorkflowCommand:
        if not argument.strip():
            raise ValueError("argument cannot be empty")
        return replace(self, arguments=self.arguments + (argument,))

    def with_arguments(self, arguments: Sequence[str]) -> WorkflowCommand:
        return replace(self, arguments=self.arguments + tuple(arguments))


@dataclass(frozen=True, slots=True)
class WorkflowArtifact:
    kind: ArtifactKind
    name: str
    path: ArtifactPath
    mime_type: str | None = None
    content_size: int | None = None
    modified_time: datetime | None = None
    checksum: str | None = None
    metadata_id: str | None = None

    def __post_init__(self) -> None:
        if not self.name.strip():
            raise ValueError("WorkflowArtifact.name cannot be empty")
        if self.content_size is not None and self.content_size < 0:
            raise ValueError("WorkflowArtifact.content_size cannot be negative")

    @property
    def is_remote(self) -> bool:
        return self.kind == ArtifactKind.REMOTE

    @property
    def is_result(self) -> bool:
        return self.kind == ArtifactKind.RESULT


@dataclass(frozen=True, slots=True)
class WorkflowParticipant:
    role: str
    name: str
    email: str | None = None
    organization_name: str | None = None
    orcid: str | None = None
    ror: str | None = None

    def __post_init__(self) -> None:
        if not self.role.strip():
            raise ValueError("WorkflowParticipant.role cannot be empty")
        if not self.name.strip():
            raise ValueError("WorkflowParticipant.name cannot be empty")


@dataclass(frozen=True, slots=True)
class WorkflowMetadata:
    name: str
    description: str = ""
    version: str | None = None
    authors: tuple[WorkflowParticipant, ...] = ()
    submitter: WorkflowParticipant | None = None
    license: str | None = None
    created_at: datetime | None = None
    generated_at: datetime | None = None
    crate_version: str | None = None
    compss_version: str | None = None
    data_persistence: DataPersistenceKind = DataPersistenceKind.UNKNOWN
    source_metadata_path: Path | None = None

    def __post_init__(self) -> None:
        if not self.name.strip():
            raise ValueError("WorkflowMetadata.name cannot be empty")

    def with_submitter(self, submitter: WorkflowParticipant | None) -> WorkflowMetadata:
        return replace(self, submitter=submitter)

    def with_authors(self, authors: Iterable[WorkflowParticipant]) -> WorkflowMetadata:
        return replace(self, authors=tuple(authors))


@dataclass(frozen=True, slots=True)
class CrateIndex:
    inputs: tuple[WorkflowArtifact, ...] = ()
    outputs: tuple[WorkflowArtifact, ...] = ()
    sources: tuple[WorkflowArtifact, ...] = ()
    remote_resources: tuple[WorkflowArtifact, ...] = ()

    def all_artifacts(self) -> tuple[WorkflowArtifact, ...]:
        return (*self.inputs, *self.outputs, *self.sources, *self.remote_resources)

    def with_inputs(self, artifacts: Iterable[WorkflowArtifact]) -> CrateIndex:
        return replace(self, inputs=tuple(artifacts))

    def with_outputs(self, artifacts: Iterable[WorkflowArtifact]) -> CrateIndex:
        return replace(self, outputs=tuple(artifacts))

    def with_sources(self, artifacts: Iterable[WorkflowArtifact]) -> CrateIndex:
        return replace(self, sources=tuple(artifacts))

    def with_remote_resources(self, artifacts: Iterable[WorkflowArtifact]) -> CrateIndex:
        return replace(self, remote_resources=tuple(artifacts))


@dataclass(frozen=True, slots=True)
class CrateSummary:
    source: CrateSource
    location: CrateLocation
    metadata: WorkflowMetadata
    index: CrateIndex = field(default_factory=CrateIndex)
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    repository_url: str | None = None
    crate_format_version: str | None = None

    def __post_init__(self) -> None:
        if self.repository_url is not None and not self.repository_url.strip():
            raise ValueError("CrateSummary.repository_url cannot be empty when provided")

    @property
    def has_inputs(self) -> bool:
        return len(self.index.inputs) > 0

    @property
    def has_outputs(self) -> bool:
        return len(self.index.outputs) > 0

    @property
    def has_remote_resources(self) -> bool:
        return len(self.index.remote_resources) > 0

    @property
    def artifact_count(self) -> int:
        return len(self.index.all_artifacts())

    def with_metadata(self, metadata: WorkflowMetadata) -> CrateSummary:
        return replace(self, metadata=metadata)

    def with_index(self, index: CrateIndex) -> CrateSummary:
        return replace(self, index=index)

    def with_location(self, location: CrateLocation) -> CrateSummary:
        return replace(self, location=location)


@dataclass(frozen=True, slots=True)
class CrateCompatibilityReport:
    compss_version_current: str | None
    compss_version_expected: str | None
    crate_format_version_current: str | None = None
    crate_format_version_expected: str | None = None
    metadata_format: str | None = None
    compatible: bool = True
    warnings: tuple[str, ...] = ()
    errors: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if self.compatible and self.errors:
            raise ValueError("A compatible report cannot contain errors")

    @property
    def has_warnings(self) -> bool:
        return len(self.warnings) > 0

    @property
    def has_errors(self) -> bool:
        return len(self.errors) > 0


__all__ = [
    "ArtifactKind",
    "ArtifactPath",
    "CrateCompatibilityReport",
    "CrateIndex",
    "CrateLocation",
    "CrateSource",
    "CrateSourceKind",
    "CrateSummary",
    "DataPersistenceKind",
    "WorkflowArtifact",
    "WorkflowCommand",
    "WorkflowMetadata",
    "WorkflowParticipant",
]