from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import runtime_checkable

from rocrate.rocrate import ROCrate

from domain.models.crate import CrateSource, CrateSourceKind


@dataclass(frozen=True, slots=True)
class SourceAcquisitionResult:
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
    file: bool
    url: bool
    message: str = ""

    @property
    def is_valid(self) -> bool:
        return self.exists and self.readable and (self.directory or self.file or self.url)

def is_remote_source(source: CrateSource) -> bool:
    return source.type == CrateSourceKind.URL


def is_local_source(source: CrateSource) -> bool:
    return source.type in {CrateSourceKind.DIRECTORY, CrateSourceKind.ZIP}


def _metadata_file_exists(root: Path) -> bool:
    return (root / "ro-crate-metadata.json").is_file() or any(root.rglob("ro-crate-metadata.json"))


def _metadata_yaml_exists(root: Path) -> bool:
    return (root / "ro-crate-metadata.json").is_file() or any(root.rglob("ro-crate-metadata.json")) or \
           (root / "ro-crate-info.yaml").is_file() or any(root.rglob("ro-crate-info.yaml"))


def load_rocrate_if_valid(root: Path) -> ROCrate | None:
    root = Path(root).expanduser()
    if not root.exists():
        return None
    if not root.is_dir():
        return None
    if not _metadata_file_exists(root) and not _metadata_yaml_exists(root):
        return None

    try:
        crate = ROCrate(root)
        return crate
    except Exception:
        return None


def ensure_rocrate(root: Path, *, name: str | None = None, description: str = "") -> ROCrate | None:
    root = Path(root).expanduser()
    root.mkdir(parents=True, exist_ok=True)

    existing = load_rocrate_if_valid(root)
    if existing is not None:
        return existing

    try:
        crate = ROCrate(root)
        dataset = crate.root_dataset

        if name:
            dataset["name"] = name
        elif not dataset.get("name"):
            dataset["name"] = root.name

        if description:
            dataset["description"] = description

        crate.write()
        return crate
    except Exception:
        return None