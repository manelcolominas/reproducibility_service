from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Protocol, runtime_checkable

from compss_rs.domain.models.crate import CrateSource, CrateSourceKind


@dataclass(frozen=True, slots=True)
class SourceAcquisitionResult:
    source: CrateSource
    source_root: Path
    prepared_root: Path
    copied: bool = False
    extracted: bool = False
    downloaded: bool = False

    def __post_init__(self) -> None:
        if not str(self.source_root).strip():
            raise ValueError("SourceAcquisitionResult.source_root cannot be empty")
        if not str(self.prepared_root).strip():
            raise ValueError("SourceAcquisitionResult.prepared_root cannot be empty")


@dataclass(frozen=True, slots=True)
class SourceValidationResult:
    source: CrateSource
    exists: bool
    readable: bool
    directory: bool
    archive: bool
    url: bool
    message: str = ""

    @property
    def is_valid(self) -> bool:
        return self.exists and self.readable and (self.directory or self.archive or self.url)


@runtime_checkable
class CrateSourceResolver(Protocol):
    def resolve(self, raw_source: str) -> CrateSource:
        ...


@runtime_checkable
class CrateSourceValidator(Protocol):
    def validate(self, source: CrateSource) -> SourceValidationResult:
        ...


@runtime_checkable
class CrateSourceAcquirer(Protocol):
    def acquire(self, source: CrateSource, destination_root: Path) -> SourceAcquisitionResult:
        ...


def is_remote_source(source: CrateSource) -> bool:
    return source.kind == CrateSourceKind.URL


def is_local_source(source: CrateSource) -> bool:
    return source.kind in {CrateSourceKind.DIRECTORY, CrateSourceKind.ZIP}