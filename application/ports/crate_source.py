from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import runtime_checkable

from rocrate.rocrate import ROCrate

from domain.models.crate import CrateSource


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

def _metadata_json_file_exists(root: Path) -> bool:
    return (root / "ro-crate-metadata.json").is_file()


def _metadata_yaml_file_exists(root: Path) -> bool:
    return (root / "ro-crate-info.yaml").is_file()


def load_rocrate_if_valid(root: Path) -> ROCrate | None:
    # if not _metadata_json_file_exists(root):
    #     raise FileNotFoundError("ro-crate-metadata.json file does not exist")

    try:
        crate = ROCrate(root)
        return crate
    except Exception:
        raise ValueError("Failed to load RO-Crate from the specified root")