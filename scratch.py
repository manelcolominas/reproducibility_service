from domain.models.crate import CrateSource
import os
from dataclasses import dataclass, replace, field
from pathlib import Path
from domain.models.crate import CrateSourceKind
from rocrate.rocrate import ROCrate
from domain.models.crate import WorkflowParticipant, DataPersistenceKind
from datetime import datetime, timezone
from domain.models.crate import CrateIndex, WorkflowArtifact


@dataclass(frozen=True, slots=True)
class SourceAcquisitionResult:
    """
    The SourceAcquisitionResult is an object whose main objective is to store how
    the crate source was obtained, whether it was downloaded, extracted, or was already on
    the disk.
    """

    source: CrateSource
    source_root: Path
    prepared_root: Path
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
        # Validate that the source_root and prepared_root are not empty.
        if not str(self.source_root).strip():
            raise ValueError("SourceAcquisitionResult.source_root cannot be empty")
        if not str(self.prepared_root).strip():
            raise ValueError("SourceAcquisitionResult.prepared_root cannot be empty")
        # Validate that the prepared_root exists on the filesystem.
        if not self.prepared_root.exists():
            raise ValueError("SourceAcquisitionResult.prepared_root does not exist")


@dataclass(frozen=True, slots=True)
class CrateSource:
    type: CrateSourceKind
    name: str
    rocrate: ROCrate | None = None

    def __post_init__(self) -> None:
        if not self.name.strip():
            raise ValueError("CrateSource.name cannot be empty")

    def with_rocrate(self, rocrate: ROCrate | None) -> "CrateSource":
        return replace(self, rocrate=rocrate)


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
class CrateSummary:
    source: CrateSource
    location: Path
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

def _metadata_json_file_exists(root: Path) -> bool:
    return (root / "ro-crate-metadata.json").is_file()


def _metadata_yaml_file_exists(root: Path) -> bool:
    return (root / "ro-crate-info.yaml").is_file()


def load_rocrate_if_valid(root: Path) -> ROCrate | None:
    if not _metadata_json_file_exists(root):
        raise FileNotFoundError("ro-crate-metadata.json file does not exist")

    try:
        crate = ROCrate(root)
        return crate
    except Exception:
        raise ValueError("Failed to load RO-Crate from the specified root")

@dataclass(frozen=True, slots=True)
class ImportCrateResult:
    source: CrateSource
    validation: SourceValidationResult
    acquisition: SourceAcquisitionResult | None
    location: Path
    crate: CrateSummary | None = None
    warnings: tuple[str, ...] = ()
    notes: tuple[str, ...] = ()
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
