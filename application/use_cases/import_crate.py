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
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
import os
import shutil
import re
from urllib import response
import zipfile
from urllib.request import Request, urlopen
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse, unquote

from rocrate.rocrate import ROCrate

from application.ports.crate_source import (
    SourceAcquisitionResult,
    SourceValidationResult,
    ensure_rocrate,
    load_rocrate_if_valid,
)
from application.ports.file_system import DirectoryCreateRequest
from domain.errors import FileSystemError, ValidationError
from domain.models.crate import (
    CrateLocation,
    CrateSource,
    CrateSummary,
    WorkflowMetadata,
    CrateSourceKind,
)

BROWSER_HEADERS = {
        "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0 Safari/537.36",
        "Accept": "application/octet-stream,application/zip,application/json,text/html,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9",
    }

class ImportCrateStatus(str, Enum):
    IMPORTED = "imported"
    FAILED = "failed"


@dataclass(frozen=True, slots=True)
class ImportCrateResult:
    status: ImportCrateStatus
    source: CrateSource
    validation: SourceValidationResult
    acquisition: SourceAcquisitionResult | None
    location: CrateLocation
    crate: CrateSummary | None = None
    warnings: tuple[str, ...] = ()
    notes: tuple[str, ...] = ()
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


def _import_rocrate_simple(source_name, workspace_directory, crate_directory, file_system):
    # take the source_name and convert it to string and remove whitespace from both ends
    raw_value = str(source_name).strip()

    # if the raw_value is empty, raise a ValidationError
    if not raw_value:
        raise ValidationError("source_name cannot be empty")

    # if the raw_value starts with "http://" or "https://", then it is a URL
    if raw_value.startswith(("http://", "https://")):
        # create a CrateSource object with type URL and value raw_value
        # CrateSourceKind is a class that defines the type of source, in this case URL
        source = CrateSource(type=CrateSourceKind.URL, value=raw_value)

        # we assume that the URL exists and is readable
        exists = readable = True

        # we set directory and file to False because it is a URL
        directory = file = False

        # we set url to True because it is a URL
        url = True
    # if the raw_value is a path to a file or directory
    else:
        # converts the raw_value to a Path object
        source_path = Path(raw_value).expanduser()

        # if the source_path has a suffix of ".zip", then it is a zip file
        if source_path.suffix.lower() == ".zip":
            # create a CrateSource object with type ZIP and value the source_path
            source = CrateSource(type=CrateSourceKind.ZIP, value=str(source_path))
            # we check if the source_path exists
            exists = source_path.exists()
            if exists:
                # we check if the source_path is readable
                readable = os.access(source_path, os.R_OK)
            else:
                readable = False
            # we set directory to False because it is a zip file
            directory = False
            # we check if the source_path is a zip file
            if exists and readable and zipfile.is_zipfile(source_path):
                    file = True
            else:
                    file = False
            url = False

        ###
        ### we could support more compressed file formats here.
        ###

        # if it is not a zip file, then source_path is assumed to be a directory
        else:
            # create a CrateSource object with type DIRECTORY and value the source_path
            source = CrateSource(type=CrateSourceKind.DIRECTORY, value=str(source_path))
            # we check if the source_path exists
            exists = source_path.exists()
            if exists:
                # we check if the source_path is readable
                readable = os.access(source_path, os.R_OK)
                # we check if the source_path is a directory
                directory = source_path.is_dir()
            else:
                # we set readable and directory to False because the source_path does not exist
                readable = False
                directory = False
            # we set file and url to False because it is a directory
            file = False
            url = False
            
    # if the source is not valid, we create a message indicating that the source is invalid
    if not (exists and readable and (directory or file or url)):
        message = f"Invalid source: {raw_value}"
    else:
        message = ""
    # a SourceValidationResult object is created with attributes shown above. 
    validation = SourceValidationResult(
        source=source,
        exists=exists,
        readable=readable,
        directory=directory,
        file=file,
        url=url,
        message=message,
    )

    if not validation.is_valid:
        raise FileSystemError("Source validation failed", details=validation.message)

    file_system.create_directory(DirectoryCreateRequest(path=workspace_directory, parents=True, exist_ok=True))

    if source.type == CrateSourceKind.DIRECTORY:
        file_system.create_directory(DirectoryCreateRequest(path=crate_directory, parents=True, exist_ok=True))
        src_path = Path(source.value).expanduser().resolve()
        dst_path = crate_directory.resolve()
    
        # If source and destination are the same directory, reuse in place.
        if src_path == dst_path:
            acquisition = SourceAcquisitionResult(
                source=source,
                source_root=src_path,
                prepared_root=dst_path,
            )
        else:
            try:
                shutil.copytree(src_path, dst_path, dirs_exist_ok=True)
            except shutil.Error as exc:
                raise FileSystemError(
                    "Could not copy crate directory",
                    details=str(exc),
                ) from exc
    
            acquisition = SourceAcquisitionResult(
                source=source,
                source_root=src_path,
                prepared_root=dst_path,
            )

    elif source.type == CrateSourceKind.ZIP:
        file_system.create_directory(DirectoryCreateRequest(path=crate_directory, parents=True, exist_ok=True))
        with zipfile.ZipFile(Path(source.value)) as archive_file:
            top_levels = {
                Path(name).parts[0]
                for name in archive_file.namelist()
                if name and not name.startswith("/") and Path(name).parts
            }
        
            if len(top_levels) == 1 and next(iter(top_levels)) == crate_directory.name:
                archive_file.extractall(crate_directory.parent)
                prepared_root = crate_directory
            else:
                archive_file.extractall(crate_directory)
                prepared_root = crate_directory

        acquisition = SourceAcquisitionResult(
            source=source,
            source_root=Path(source.value),
            prepared_root=crate_directory,
            extracted=True,
        )

    else:
        request = Request(source.value, headers=BROWSER_HEADERS, method="GET")
        try:
            with urlopen(request, timeout=30) as response:
                download_bytes = response.read()
                downloaded_filename = _filename_from_http_response(response, source.value)
        except (HTTPError, URLError, OSError) as exc:
            raise FileSystemError("Could not download crate source", details=str(exc)) from exc

        final_dirname = _crate_dirname_from_downloaded_filename(downloaded_filename)
        final_crate_directory = crate_directory.parent / final_dirname
        file_system.create_directory(DirectoryCreateRequest(path=final_crate_directory, parents=True, exist_ok=True))
        
        temp_zip = final_crate_directory.parent / ".downloaded_rocrate.zip"
        temp_zip.write_bytes(download_bytes)
        try:
            if zipfile.is_zipfile(temp_zip):
                with zipfile.ZipFile(temp_zip) as archive_file:
                    archive_file.extractall(final_crate_directory)
                prepared_root = final_crate_directory
                extracted = True
            else:
                target = final_crate_directory / "downloaded_crate"
                target.write_bytes(download_bytes)
                prepared_root = final_crate_directory
                extracted = False
        finally:
            temp_zip.unlink(missing_ok=True)

        acquisition = SourceAcquisitionResult(
            source=source,
            source_root=Path(source.value),
            prepared_root=prepared_root,
            downloaded=True,
            extracted=extracted,
        )

    location = CrateLocation(
        original_path=acquisition.source_root,
        crate_path=acquisition.prepared_root,
    )

    rocrate = load_rocrate_if_valid(location.crate_path)
    if rocrate is None:
        rocrate = ensure_rocrate(
            location.crate_path,
            name=location.crate_path.name,
            description=f"Imported crate from {source.value}",
        )

    source_with_rocrate = source.with_rocrate(rocrate)

    metadata = WorkflowMetadata(
        name=(rocrate.root_dataset.get("name") if rocrate else location.crate_path.name) or "unnamed-workflow",
        description=str((rocrate.root_dataset.get("description") if rocrate else "") or ""),
        source_metadata_path=location.crate_path / "ro-crate-metadata.json",
        rocrate=rocrate,
    )

    crate = CrateSummary(
        source=source_with_rocrate,
        location=location,
        metadata=metadata,
        rocrate=rocrate,
    )

    return ImportCrateResult(
        status=ImportCrateStatus.IMPORTED,
        source=source_with_rocrate,
        validation=validation,
        acquisition=acquisition,
        location=location,
        crate=crate,
        notes=("Crate source prepared successfully",),
    )


def _filename_from_http_response(response, source_url: str) -> str | None:
    content_disposition = response.headers.get("Content-Disposition", "")
    # RFC 5987: filename*=UTF-8''workflow-635-1.crate.zip
    match = re.search(r"filename\*\s*=\s*[^']*''([^;]+)", content_disposition, flags=re.IGNORECASE)
    if match:
        return Path(unquote(match.group(1).strip().strip('"'))).name

    # Legacy: filename="workflow-635-1.crate.zip" or filename=workflow-635-1.crate.zip
    match = re.search(r'filename\s*=\s*"([^"]+)"', content_disposition, flags=re.IGNORECASE)
    if not match:
        match = re.search(r"filename\s*=\s*([^;]+)", content_disposition, flags=re.IGNORECASE)
    if match:
        return Path(unquote(match.group(1).strip().strip('"'))).name

    # Fallback to URL path
    fallback = Path(unquote(urlparse(source_url).path)).name.strip()
    return fallback or None

    
def _crate_dirname_from_downloaded_filename(filename: str | None) -> str:
    if not filename:
        return ".crate_downloaded"

    name = filename.strip()
    if name.lower().endswith(".zip"):
        name = name[:-4].strip()

    if not name:
        return ".crate_downloaded"

    # Prevent path traversal or slashes in header value
    return Path(name).name or ".crate_downloaded"
