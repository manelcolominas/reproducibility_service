from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, Mapping, Protocol, runtime_checkable

from compss_rs.domain.errors import MetadataError, MetadataParseError, ValidationError
from compss_rs.domain.models.crate import (
    CrateIndex,
    CrateSummary,
    DataPersistenceKind,
    WorkflowArtifact,
    WorkflowMetadata,
    WorkflowParticipant,
)


class MetadataFormat(str, Enum):
    ROCRATE_JSON = "rocrate_json"
    COMPSS_INFO_YAML = "compss_info_yaml"
    LEGACY_YAML = "legacy_yaml"
    LEGACY_JSON = "legacy_json"
    UNKNOWN = "unknown"


class MetadataSourceKind(str, Enum):
    FILE = "file"
    DIRECTORY = "directory"
    ARCHIVE = "archive"
    URL = "url"
    MEMORY = "memory"


class MetadataConfidence(str, Enum):
    EXACT = "exact"
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


@dataclass(frozen=True, slots=True)
class MetadataSource:
    kind: MetadataSourceKind
    location: str
    format_hint: MetadataFormat = MetadataFormat.UNKNOWN
    description: str | None = None

    def __post_init__(self) -> None:
        if not self.location.strip():
            raise ValidationError("MetadataSource.location cannot be empty")


@dataclass(frozen=True, slots=True)
class MetadataFieldMatch:
    canonical_name: str
    matched_name: str
    value: Any
    confidence: MetadataConfidence = MetadataConfidence.MEDIUM
    source: str | None = None

    def __post_init__(self) -> None:
        if not self.canonical_name.strip():
            raise ValidationError("MetadataFieldMatch.canonical_name cannot be empty")
        if not self.matched_name.strip():
            raise ValidationError("MetadataFieldMatch.matched_name cannot be empty")


@dataclass(frozen=True, slots=True)
class MetadataParseIssue:
    code: str
    message: str
    path: str | None = None
    details: str | None = None

    def __post_init__(self) -> None:
        if not self.code.strip():
            raise ValidationError("MetadataParseIssue.code cannot be empty")
        if not self.message.strip():
            raise ValidationError("MetadataParseIssue.message cannot be empty")


@dataclass(frozen=True, slots=True)
class MetadataDocument:
    source: MetadataSource
    format: MetadataFormat
    raw: Mapping[str, Any]
    path: Path | None = None
    encoding: str = "utf-8"
    fields: tuple[MetadataFieldMatch, ...] = ()
    issues: tuple[MetadataParseIssue, ...] = ()

    def __post_init__(self) -> None:
        if self.format == MetadataFormat.UNKNOWN:
            raise ValidationError("MetadataDocument.format cannot be UNKNOWN")

    @property
    def has_issues(self) -> bool:
        return len(self.issues) > 0

    @property
    def is_empty(self) -> bool:
        return len(self.raw) == 0


@dataclass(frozen=True, slots=True)
class MetadataNormalizationResult:
    document: MetadataDocument
    metadata: WorkflowMetadata | None = None
    index: CrateIndex | None = None
    crate: CrateSummary | None = None
    warnings: tuple[str, ...] = ()
    issues: tuple[MetadataParseIssue, ...] = ()

    @property
    def is_usable(self) -> bool:
        return self.metadata is not None or self.crate is not None


@dataclass(frozen=True, slots=True)
class MetadataParseRequest:
    source: MetadataSource
    expected_format: MetadataFormat = MetadataFormat.UNKNOWN
    allow_legacy_fields: bool = True
    allow_partial_metadata: bool = True
    strict: bool = False

    def __post_init__(self) -> None:
        if not self.source.location.strip():
            raise ValidationError("MetadataParseRequest.source.location cannot be empty")


@dataclass(frozen=True, slots=True)
class MetadataNormalizationOptions:
    resolve_field_aliases: bool = True
    prefer_submitter_over_agent: bool = True
    allow_multiple_authors: bool = True
    infer_data_persistence: bool = True
    preserve_unknown_fields: bool = True
    collect_warnings: bool = True


@dataclass(frozen=True, slots=True)
class MetadataFieldMap:
    canonical_name: str
    aliases: tuple[str, ...] = ()
    required: bool = False
    multi_valued: bool = False

    def __post_init__(self) -> None:
        if not self.canonical_name.strip():
            raise ValidationError("MetadataFieldMap.canonical_name cannot be empty")
        if not self.aliases:
            raise ValidationError("MetadataFieldMap.aliases cannot be empty")


@dataclass(frozen=True, slots=True)
class MetadataSchema:
    name: str
    fields: tuple[MetadataFieldMap, ...] = ()
    version: str | None = None
    description: str | None = None

    def __post_init__(self) -> None:
        if not self.name.strip():
            raise ValidationError("MetadataSchema.name cannot be empty")

    def required_fields(self) -> tuple[MetadataFieldMap, ...]:
        return tuple(field for field in self.fields if field.required)


@dataclass(frozen=True, slots=True)
class ParsedParticipantRecord:
    role: str
    name: str
    email: str | None = None
    organization_name: str | None = None
    orcid: str | None = None
    ror: str | None = None

    def to_domain(self) -> WorkflowParticipant:
        return WorkflowParticipant(
            role=self.role,
            name=self.name,
            email=self.email,
            organization_name=self.organization_name,
            orcid=self.orcid,
            ror=self.ror,
        )


@dataclass(frozen=True, slots=True)
class ParsedArtifactRecord:
    kind: str
    name: str
    path: str
    metadata_id: str | None = None
    mime_type: str | None = None
    content_size: int | None = None
    checksum: str | None = None
    source_kind: str | None = None

    def to_domain(self, resolved_path: Path | None = None) -> WorkflowArtifact:
        from compss_rs.domain.models.crate import ArtifactKind, ArtifactPath

        artifact_kind = ArtifactKind(self.kind) if self.kind in ArtifactKind._value2member_map_ else ArtifactKind.OTHER
        artifact_path = ArtifactPath(relative_path=self.path, resolved_path=resolved_path)
        return WorkflowArtifact(
            kind=artifact_kind,
            name=self.name,
            path=artifact_path,
            mime_type=self.mime_type,
            content_size=self.content_size,
            checksum=self.checksum,
            metadata_id=self.metadata_id,
        )


@runtime_checkable
class MetadataParser(Protocol):
    def parse(self, request: MetadataParseRequest) -> MetadataDocument:
        """
        Parse metadata from the given source into a raw document representation.
        """
        ...


@runtime_checkable
class MetadataNormalizer(Protocol):
    def normalize(self, document: MetadataDocument, options: MetadataNormalizationOptions) -> MetadataNormalizationResult:
        """
        Normalize a raw metadata document into canonical domain models.
        """
        ...


@runtime_checkable
class MetadataFieldResolver(Protocol):
    def resolve(self, document: MetadataDocument, schema: MetadataSchema) -> tuple[MetadataFieldMatch, ...]:
        """
        Resolve canonical fields from a raw metadata document.
        """
        ...


@runtime_checkable
class MetadataInspector(Protocol):
    def inspect(self, document: MetadataDocument) -> tuple[MetadataParseIssue, ...]:
        """
        Validate a document for structural and semantic metadata problems.
        """
        ...


class MetadataPortError(MetadataError):
    pass


class UnsupportedMetadataSourceError(MetadataPortError):
    def __init__(self, source: MetadataSource, details: str | None = None):
        super().__init__(
            message=f"Unsupported metadata source: {source.location}",
            details=details,
            recoverable=False,
        )


class UnsupportedMetadataFormatPortError(MetadataPortError):
    def __init__(self, format_name: str, details: str | None = None):
        super().__init__(
            message=f"Unsupported metadata format: {format_name}",
            details=details,
            recoverable=False,
        )


class IncompleteMetadataError(MetadataPortError):
    def __init__(self, message: str, details: str | None = None):
        super().__init__(
            message=message,
            details=details,
            recoverable=True,
        )


def has_metadata_issues(document: MetadataDocument) -> bool:
    return document.has_issues


def is_rocrate_metadata(format_kind: MetadataFormat) -> bool:
    return format_kind == MetadataFormat.ROCRATE_JSON


def is_yaml_metadata(format_kind: MetadataFormat) -> bool:
    return format_kind in {MetadataFormat.COMPSS_INFO_YAML, MetadataFormat.LEGACY_YAML}


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


__all__ = [
    "IncompleteMetadataError",
    "MetadataConfidence",
    "MetadataDocument",
    "MetadataFieldMap",
    "MetadataFieldMatch",
    "MetadataFieldResolver",
    "MetadataFormat",
    "MetadataInspector",
    "MetadataNormalizationOptions",
    "MetadataNormalizationResult",
    "MetadataNormalizer",
    "MetadataParseIssue",
    "MetadataParseRequest",
    "MetadataPortError",
    "MetadataSchema",
    "MetadataSource",
    "MetadataSourceKind",
    "MetadataParser",
    "ParsedArtifactRecord",
    "ParsedParticipantRecord",
    "build_workflow_metadata",
    "has_metadata_issues",
    "is_rocrate_metadata",
    "is_yaml_metadata",
    "UnsupportedMetadataFormatPortError",
    "UnsupportedMetadataSourceError",
]