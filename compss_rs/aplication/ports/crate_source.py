from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Protocol, runtime_checkable

from compss_rs.domain.models.crate import CrateSource, CrateSourceKind
from compss_rs.domain.errors import FileSystemError, NetworkError, ValidationError


@dataclass(frozen=True, slots=True)
class SourceAcquisitionResult:
    source: CrateSource
    source_root: Path
    prepared_root: Path
    is_archive: bool = False
    was_downloaded: bool = False
    was_extracted: bool = False

    def __post_init__(self) -> None:
        if not str(self.source_root).strip():
            raise ValidationError("source_root cannot be empty")
        if not str(self.prepared_root).strip():
            raise ValidationError("prepared_root cannot be empty")


@dataclass(frozen=True, slots=True)
class SourceValidationResult:
    source: CrateSource
    exists: bool
    readable: bool
    is_directory: bool
    is_archive: bool
    is_url: bool
    errors: tuple[str, ...] = ()

    @property
    def is_valid(self) -> bool:
        return self.exists and self.readable and (self.is_directory or self.is_archive or self.is_url)


@runtime_checkable
class CrateSourceResolver(Protocol):
    def resolve(self, raw_source: str) -> CrateSource:
        """
        Convert user input into a canonical CrateSource object.
        """
        ...


@runtime_checkable
class CrateSourceValidator(Protocol):
    def validate(self, source: CrateSource) -> SourceValidationResult:
        """
        Validate that a crate source can be consumed by the application.
        """
        ...


@runtime_checkable
class CrateSourceAcquirer(Protocol):
    def acquire(self, source: CrateSource, destination_root: Path) -> SourceAcquisitionResult:
        """
        Prepare a crate source inside the working directory.
        """
        ...


@runtime_checkable
class CrateSourceCleaner(Protocol):
    def cleanup(self, prepared_root: Path) -> None:
        """
        Remove temporary artifacts created while preparing the source.
        """
        ...


@runtime_checkable
class CrateSourceInspector(Protocol):
    def inspect(self, prepared_root: Path) -> SourceValidationResult:
        """
        Inspect a prepared source and report structural validity.
        """
        ...


class UnsupportedCrateSourceError(ValidationError):
    def __init__(self, source: str, details: str | None = None):
        super().__init__(
            message=f"Unsupported crate source: {source}",
            details=details,
            recoverable=False,
        )


class CrateSourcePortError(FileSystemError):
    pass


def is_remote_source(source: CrateSource) -> bool:
    return source.kind in {CrateSourceKind.URL, CrateSourceKind.REMOTE_PROVIDER}


def is_local_source(source: CrateSource) -> bool:
    return source.kind in {CrateSourceKind.LOCAL_DIRECTORY, CrateSourceKind.ZIP_ARCHIVE}


__all__ = [
    "CrateSourceAcquirer",
    "CrateSourceCleaner",
    "CrateSourceInspector",
    "CrateSourcePortError",
    "CrateSourceResolver",
    "CrateSourceValidator",
    "SourceAcquisitionResult",
    "SourceValidationResult",
    "UnsupportedCrateSourceError",
    "is_local_source",
    "is_remote_source",
]