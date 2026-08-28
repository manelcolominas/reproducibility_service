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
from io import BytesIO
import json
from pathlib import Path
import os
import shutil
import re
import requests
import zipfile
from urllib.request import Request, urlopen
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse, unquote

from application.ports.crate_source import (
    SourceAcquisitionResult,
    SourceValidationResult,
    ensure_rocrate,
    load_rocrate_if_valid,
)
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
        source = CrateSource(type=CrateSourceKind.URL, name=raw_value)

        # we assume that the URL exists and is readable
        exists = readable = True

        # we set directory and file to False because it is a URL
        directory = file = False

        # we set url to True because it is a URL
        url = True
    # if the raw_value is a path to a file or directory
    else:
        # converts the raw_value to a Path object
        source_relative_path = Path(raw_value).expanduser()

        # if the source_relative_path has a suffix of ".zip", then it is a zip file
        if source_relative_path.suffix.lower() == ".zip":
            # create a CrateSource object with type ZIP and value the source_relative_path
            source = CrateSource(type=CrateSourceKind.ZIP, name=str(source_relative_path))
            # we check if the source_relative_path exists
            exists = source_relative_path.exists()
            if exists:
                # we check if the source_relative_path is readable
                readable = os.access(source_relative_path, os.R_OK)
            else:
                readable = False
            # we set directory to False because it is a zip file
            directory = False
            # we check if the source_relative_path is a zip file
            if exists and readable and zipfile.is_zipfile(source_relative_path):
                    file = True
            else:
                    file = False
            url = False

        ###
        ### we could support more compressed file formats here.
        ###

        # if it is not a zip file, then source_relative_path is assumed to be a directory
        else:
            # create a CrateSource object with type DIRECTORY and value the source_relative_path
            source = CrateSource(type=CrateSourceKind.DIRECTORY, name=str(source_relative_path))
            # we check if the source_relative_path exists
            exists = source_relative_path.exists()
            if exists:
                # we check if the source_relative_path is readable
                readable = os.access(source_relative_path, os.R_OK)
                # we check if the source_relative_path is a directory
                directory = source_relative_path.is_dir()
            else:
                # we set readable and directory to False because the source_relative_path does not exist
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
    # that basically stores the bool values of the source validation checks, if it exists, 
    # if it is readable, if it is a directory, if it is a file, if it is a url and a message.
    validation = SourceValidationResult(source=source, exists=exists,readable=readable,directory=directory,file=file,url=url,message=message)

    # we call the function is_valid from the SourceValidationResult class to check if the source
    # is valid, if not we raise a FileSystemError with the message from the validation object.
    if not validation.is_valid:
        raise FileSystemError("Source validation failed", details=validation.message)

    # we create the workspace directory (reproducibility_service_{run_id}) if it does not exist,
    #  using the create_directory function from the file_system object
    file_system.create_directory(path=workspace_directory, parents=True, exist_ok=True)
    # we get the absolute path of the source
    source_absolute_path = Path(source.name).expanduser().resolve()
    # we get the absolute path of the crate directory
    destination_absolute_path = crate_directory.resolve()

    # if the source is a directory we enter into this block
    if source.type == CrateSourceKind.DIRECTORY:
        # we create the crate directory if it does not exist, using the create_directory function from
        # the file_system object
        file_system.create_directory(path=crate_directory, parents=True, exist_ok=True)

        # we create a SourceAcquisitionResult object to store the source, the absolute path of the source,
        #############################################################
        #  and the absolute path of the prepared root directory. ????????
        #################################################################
        acquisition = SourceAcquisitionResult(source=source, source_root=source_absolute_path, prepared_root=destination_absolute_path)

    # if the source is a zip file we enter into this block
    elif source.type == CrateSourceKind.ZIP:
        # we create a ZipFile object from the source name
        archive_file = zipfile.ZipFile(Path(source.name))
        # we extract all the contents of the zip file into the parent directory of the crate directory
        # is very important to extract them in the parent directory of the crate directory
        # not in the crate directory itself
        # if we do it in the crate directory itself, it will get a double nested structure like this :
        # RO-Crate 
        #   └── RO-Crate
        #       │   ├── application_sources
        #       │   ├── pom.xml
        #       │   ├── README
        #       │   └── src
        #       │       └── wordcount.py
        #       ├── App_Profile.json
        #       ├── complete_graph.svg
        #       ├── compss_submission_command_line.txt
        #       ├── dataset
        #       │   └── data
        #       │       ├── file0.txt
        #       │       ├── file1.txt
        #       │       ├── file2.txt
        #       │       └── file3.txt
        #       ├── ro-crate-info.yaml
        #       ├── ro-crate-metadata.json
        #       └── ro-crate-preview.html

        # therefore, we extract it in the parent directory of the crate directory
        archive_file.extractall(crate_directory.parent)
        # we get a structure like this :
        # parent_directory
        #       └── RO-Crate
        #           │   ├── application_sources
        #           │   ├── pom.xml
        #           │   ├── README
        #           │   └── src
        #           │       └── wordcount.py
        #           ├── App_Profile.json
        #           ├── complete_graph.svg
        #           ├── compss_submission_command_line.txt
        #           ├── dataset
        #           │   └── data
        #           │       ├── file0.txt
        #           │       ├── file1.txt
        #           │       ├── file2.txt
        #           │       └── file3.txt
        #           ├── ro-crate-info.yaml
        #           ├── ro-crate-metadata.json
        #           └── ro-crate-preview.html

        # we create a SourceAcquisitionResult object where we store the source that it is a CrateSource Object, wich it is : 
        #  CrateSource(type=CrateSourceKind.ZIP, name=str(source_relative_path))
        #  the absolute path of the source,
        #  whether the source was extracted or not.
        #######################################################
        #  and the absolute path of the prepared root directory. ???????????????
        #########################################################
        acquisition = SourceAcquisitionResult(source=source,source_root=source_absolute_path,prepared_root=destination_absolute_path,extracted=True)

    else:
        # we create a Request object to download the crate source from the given URL
        # this creates an HTTP GET request.
        # HTTP Packet:
        # GET /workflows/635/ro_crate?version=1 HTTP/1.1
        #     Request Method: GET
        #     Request URI: /workflows/635/ro_crate?version=1
        # User-Agent: "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0 Safari/537.36",
        # Accept: "application/octet-stream,application/zip,application/json,text/html,*/*;q=0.8",
        # Accept-Language: en-US,en;q=0.9

        # which is the :
        # REQUEST METHOD + REQUEST URI
        #        Request Method: METHOD
        #        Request URI: URI
        # BROWSER HEADERS

        request = Request(source.name, headers=BROWSER_HEADERS, method="GET")
        # try to download the crate source from the given URL
        try:
            # send the HTTP GET request and wait for the response from the server maximum 30 seconds
            response = urlopen(request, timeout=30)
            # read the response content
            download_bytes = response.read()
            # we call _filename_from_http_response to determine the filename for the downloaded 
            # content based on the server's response and the source name (https://workflows/635/ro_crate?version=1)
            downloaded_filename = _filename_from_http_response(response)

        # if an exception occurs during the download, it will be caught here
        except (HTTPError, URLError, OSError) as exc:
            raise FileSystemError("Could not download crate source", details=str(exc)) from exc

        # determine the final directory name for the crate based on the downloaded filename
        final_dirname = _crate_dirname_from_downloaded_filename(filename=downloaded_filename)
        # build the final crate directory path based on the parent directory and the final directory name
        final_crate_directory = crate_directory.parent / final_dirname

        # create the final crate directory if it doesn't exist using the function create_directory from the file system object
        file_system.create_directory(path=final_crate_directory, parents=True, exist_ok=True)

        # attempt to extract the downloaded archive into the final crate directory
        try:
            # open the downloaded bytes as a zip archive
            archive_file = zipfile.ZipFile(BytesIO(download_bytes))
            # extract all contents of the zip archive into the final crate directory
            archive_file.extractall(final_crate_directory)
            # set the prepared root to the final crate directory
            prepared_root = final_crate_directory
            # mark the extraction as successful
            extracted = True
        # if a BadZipFile exception occurs, it will be caught here and a FileSystemError will be raised
        except zipfile.BadZipFile as exc:
            raise FileSystemError("Failed to extract crate.", details=str(exc)) from exc

        # create the SourceAcquisitionResult object
        acquisition = SourceAcquisitionResult(source=source,source_root=source_absolute_path,prepared_root=prepared_root,downloaded=True,extracted=extracted)

    ###################################
    ######################################
    ########################################
    
    #create a CrateLocation object based on the acquisition result
    location = CrateLocation(original_path=acquisition.source_root,crate_path=acquisition.prepared_root)

    # load the RO-Crate
    # will return RO-Crate object if valid, otherwise None
    rocrate = load_rocrate_if_valid(location.crate_path)
    if rocrate is None:
        # if the RO-Crate is not valid, ensure a new RO-Crate is created
        rocrate = ensure_rocrate(location.crate_path,name=location.crate_path.name,description=f"Imported crate from {source.name}")

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


def _filename_from_http_response(response: requests.Response) -> str | None:
    # response.headers example:
    # "headers": {
    #     "Date": "Fri, 28 Aug 2026 14:06:01 GMT",
    #     "Content-Type": "application/zip",
    #     "Content-Length": "19366",
    #     "Connection": "close",
    #     "Server": "cloudflare",
    #     "Cache-Control": "no-cache",
    #     "Referrer-Policy": "strict-origin-when-cross-origin",
    #     "X-Permitted-Cross-Domain-Policies": "none",
    #     "X-XSS-Protection": "0",
    #     "X-Request-Id": "2b3673ce-44ed-4e5a-9fb1-c0f7582240f8",
    #     "Content-Disposition": "inline; filename=\"workflow-635-1.crate.zip\"; filename*=UTF-8''workflow-635-1.crate.zip",
    #     "Content-Transfer-Encoding": "binary",
    #     "X-Runtime": "0.605155",
    #     "X-Frame-Options": "SAMEORIGIN",
    #     "X-Content-Type-Options": "nosniff",
    #     "X-Powered-By": "Phusion Passenger(R) 6.0.24",
    #     "Set-Cookie": "_seek_session=e73a1e03ec251c26423998237c9976e8; path=/; expires=Fri, 28 Aug 2026 14:36:01 GMT; HttpOnly; SameSite=Lax",
    #     "Nel": "{\"report_to\":\"cf-nel\",\"success_fraction\":0.0,\"max_age\":604800}",
    #     "Status": "200 OK",
    #     "Report-To": "{\"group\":\"cf-nel\",\"max_age\":604800,\"endpoints\":[{\"url\":\"https://a.nel.cloudflare.com/report/v4?s=VVXEl3IJoDucnt1vQDavjPOkN4mrVc5vsZwugVruJUvgz4OoLdc7%2B1ebknywvKgxO6a8Kdi1KwGw8LLU8Q%2FFbmP5QDyONRxlk35qMvFcnEbRYGm27WpyD3Zk9eOPqLEX8g%3D%3D\"}]}",
    #     "cf-cache-status": "DYNAMIC",
    #     "CF-RAY": "a323dfc518da3ed1-MAD",
    #     "alt-svc": "h3=\":443\"; ma=86400"
    # }

    # from the response.headers, we get the field "Content-Disposition" which may contain the filename
    content_disposition = response.headers.get("Content-Disposition", "")

    # initialize the filename variable to None
    filename = None
    # tries to extract the filename from the Content-Disposition header using RFC 5987 format
    # filename*=UTF-8\'\'workflow-635-1.crate.zip'
    match = re.search(r"filename\*\s*=\s*[^']*''([^;]+)", content_disposition, flags=re.IGNORECASE)
    if match:
         filename = Path(unquote(match.group(1).strip().strip('"'))).name

    # filename="workflow-635-1.crate.zip" (with quotes)
    match = re.search(r'filename\s*=\s*"([^"]+)"', content_disposition, flags=re.IGNORECASE)
    if not match:
        # Legacy: filename=workflow-635-1.crate.zip (without quotes)
        match = re.search(r"filename\s*=\s*([^;]+)", content_disposition, flags=re.IGNORECASE)

    if match:
        filename = Path(unquote(match.group(1).strip().strip('"'))).name

    # Fallback to URL path if no filename could be determined from the headers
    # https://workflowhub.org/workflows/635/ro_crate?version=1 --> fallback = ro_crate
    # fallback = Path(unquote(urlparse(source_url).path)).name.strip()
    # return fallback or None
    return filename

    
def _crate_dirname_from_downloaded_filename(filename: str | None) -> str:

    # if the filename is None, we use a default name "Ro-Crate"
    if filename is None:
        name = "Ro-Crate"
    else:
        # strip any leading and trailing whitespace from the filename
        name = filename.strip()
        # check ".zip" extension
        if name.lower().endswith(".zip"):
            # remove the ".zip" extension
            name = name[:-4].strip()
        # if the resulting name is empty, fallback to the default name "Ro-Crate"
        if not name:
            name  = "Ro-Crate"
    # return the final crate directory name
    return name
