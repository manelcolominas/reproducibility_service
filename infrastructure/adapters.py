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

import json
import os
import shutil
import subprocess
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from urllib.error import URLError
from urllib.request import Request, urlopen, urlretrieve
from urllib.error import HTTPError
from tempfile import NamedTemporaryFile

import yaml

from application.ports.crate_source import (
    SourceAcquisitionResult,
    SourceValidationResult,
)
from application.ports.executor import ExecutionOutcome
from application.ports.file_system import (
    CopyRequest,
    DeleteRequest,
    DirectoryCreateRequest,
    DirectoryEntry,
    FileMetadata,
    FileSystemOperationResult,
    MoveRequest,
)
from application.ports.metadata_parser import (
    MetadataDocument,
    MetadataFormat,
    MetadataNormalizationResult,
    MetadataParseRequest,
)
from domain.errors import (
    MetadataParseError,
    SourceAcquisitionError,
    UnsupportedSourceError,
)
from domain.models.crate import (
    ArtifactKind,
    CrateIndex,
    CrateLocation,
    CrateSource,
    CrateSourceKind,
    CrateSummary,
    DataPersistenceKind,
    WorkflowArtifact,
    WorkflowMetadata,
    WorkflowParticipant,
)
from application.ports.executor import ExecutionSubmission
from domain.models.execution import (
    ExecutionBackend,
    ExecutionContext,
    ExecutionLog,
    ExecutionResult,
    ExecutionStatus,
)

BROWSER_HEADERS = {
        "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0 Safari/537.36",
        "Accept": "application/octet-stream,application/zip,application/json,text/html,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9",
    }

# --------------------------------------------------------------------------- #
# File system adapter
# --------------------------------------------------------------------------- #


class LocalFileSystem:
    """Filesystem adapter backed by pathlib/shutil (implements FileSystemManager)."""

    def exists(self, path: Path) -> bool:
        return Path(path).exists()

    def metadata(self, path: Path) -> FileMetadata:
        path = Path(path)
        exists = path.exists()
        return FileMetadata(
            path=path,
            exists=exists,
            is_file=path.is_file() if exists else False,
            is_directory=path.is_dir() if exists else False,
            readable=os.access(path, os.R_OK) if exists else False,
            writable=os.access(path, os.W_OK) if exists else False,
            size_bytes=path.stat().st_size if exists and path.is_file() else None,
        )

    def is_file(self, path: Path) -> bool:
        return Path(path).is_file()

    def is_directory(self, path: Path) -> bool:
        return Path(path).is_dir()

    def read_text(self, path: Path, encoding: str = "utf-8") -> str:
        return Path(path).read_text(encoding=encoding)

    def list_directory(self, path: Path) -> tuple[DirectoryEntry, ...]:
        entries = []
        for child in sorted(Path(path).iterdir()):
            entries.append(
                DirectoryEntry(
                    path=child,
                    name=child.name,
                    is_file=child.is_file(),
                    is_directory=child.is_dir(),
                    size_bytes=child.stat().st_size if child.is_file() else None,
                )
            )
        return tuple(entries)

    def create_directory(self, request: DirectoryCreateRequest) -> FileSystemOperationResult:
        try:
            Path(request.path).mkdir(parents=request.parents, exist_ok=request.exist_ok)
            return FileSystemOperationResult(path=request.path, succeeded=True)
        except OSError as exc:
            return FileSystemOperationResult(path=request.path, succeeded=False, message=str(exc))

    def copy(self, request: CopyRequest) -> FileSystemOperationResult:
        source, destination = Path(request.source), Path(request.destination)
        try:
            if destination.exists() and not request.overwrite:
                return FileSystemOperationResult(
                    path=destination, succeeded=False, message="Destination already exists"
                )
            destination.parent.mkdir(parents=True, exist_ok=True)
            if source.is_dir():
                if not request.recursive:
                    return FileSystemOperationResult(
                        path=destination, succeeded=False, message="Cannot copy a directory non-recursively"
                    )
                if destination.exists():
                    shutil.rmtree(destination)
                shutil.copytree(source, destination)
                size = None
            else:
                shutil.copy2(source, destination)
                size = destination.stat().st_size
            return FileSystemOperationResult(path=destination, succeeded=True, bytes_transferred=size)
        except OSError as exc:
            return FileSystemOperationResult(path=destination, succeeded=False, message=str(exc))

    def move(self, request: MoveRequest) -> FileSystemOperationResult:
        source, destination = Path(request.source), Path(request.destination)
        try:
            if destination.exists() and not request.overwrite:
                return FileSystemOperationResult(
                    path=destination, succeeded=False, message="Destination already exists"
                )
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(source), str(destination))
            return FileSystemOperationResult(path=destination, succeeded=True)
        except OSError as exc:
            return FileSystemOperationResult(path=destination, succeeded=False, message=str(exc))

    def delete(self, request: DeleteRequest) -> FileSystemOperationResult:
        path = Path(request.path)
        try:
            if not path.exists():
                if request.missing_ok:
                    return FileSystemOperationResult(path=path, succeeded=True, message="Already absent")
                return FileSystemOperationResult(path=path, succeeded=False, message="Path does not exist")
            if path.is_dir():
                if request.recursive:
                    shutil.rmtree(path)
                else:
                    path.rmdir()
            else:
                path.unlink()
            return FileSystemOperationResult(path=path, succeeded=True)
        except OSError as exc:
            return FileSystemOperationResult(path=path, succeeded=False, message=str(exc))

    def write_text(self, path: Path, content: str, encoding: str = "utf-8") -> FileSystemOperationResult:
        path = Path(path)
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(content, encoding=encoding)
            return FileSystemOperationResult(path=path, succeeded=True, bytes_transferred=len(content))
        except OSError as exc:
            return FileSystemOperationResult(path=path, succeeded=False, message=str(exc))

    def join(self, *parts: Path | str) -> Path:
        return Path(*[str(part) for part in parts])

    def resolve(self, path: Path, strict: bool = False) -> Path:
        return Path(path).resolve(strict=strict)

    def relative_to(self, path: Path, base: Path) -> Path:
        return Path(path).relative_to(base)


# --------------------------------------------------------------------------- #
# Crate source adapters (resolve / validate / acquire)
# --------------------------------------------------------------------------- #


class LocalCrateSourceResolver:
    """Turns a raw CLI argument into a typed CrateSource."""

    def resolve(self, raw_source: str) -> CrateSource:
        value = raw_source.strip()
        if value.startswith(("http://", "https://")):
            return CrateSource(type=CrateSourceKind.URL, value=value)
        if value.lower().endswith(".zip"):
            return CrateSource(type=CrateSourceKind.ZIP, value=str(Path(value).expanduser()))
        return CrateSource(type=CrateSourceKind.DIRECTORY, value=str(Path(value).expanduser()))


class LocalCrateSourceValidator:
    """Checks that a resolved CrateSource is actually usable."""

    def validate(self, source: CrateSource) -> SourceValidationResult:
        if source.type == CrateSourceKind.DIRECTORY:
            return self._validate_directory(source)
        if source.type == CrateSourceKind.ZIP:
            return self._validate_zip(source)
        if source.type == CrateSourceKind.URL:
            return self._validate_url(source)
        raise UnsupportedSourceError(f"Unsupported crate source type: {source.type}")

    def _validate_directory(self, source: CrateSource) -> SourceValidationResult:
        path = Path(source.value)
        exists = path.exists()
        directory = path.is_dir() if exists else False
        readable = os.access(path, os.R_OK) if exists else False
        message = "" if exists and directory else f"Directory not found: {path}"
        return SourceValidationResult(
            source=source, exists=exists, readable=readable, directory=directory,
            archive=False, url=False, message=message,
        )

    def _validate_zip(self, source: CrateSource) -> SourceValidationResult:
        path = Path(source.value)
        exists = path.exists()
        readable = os.access(path, os.R_OK) if exists else False
        archive = exists and readable and zipfile.is_zipfile(path)
        message = "" if archive else f"Not a valid zip archive: {path}"
        return SourceValidationResult(
            source=source, exists=exists, readable=readable, directory=False,
            archive=archive, url=False, message=message,
        )
    
    def _validate_url(self, source: CrateSource) -> SourceValidationResult:
        reachable = False
        for method in ("HEAD", "GET"):
            try:
                request = Request(source.value, method=method, headers=BROWSER_HEADERS)
                with urlopen(request, timeout=15) as response:
                    status = getattr(response, "status", None) or response.getcode()
                    if 200 <= status < 400:
                        reachable = True
                        break
            except HTTPError as exc:
                if method == "HEAD":
                    continue
                reachable = False
                break
            except (URLError, ValueError, OSError):
                reachable = False
                break
    
        message = "" if reachable else f"Could not reach URL: {source.value}"
        return SourceValidationResult(
            source=source,
            exists=reachable,
            readable=reachable,
            directory=False,
            archive=False,
            url=True,
            message=message,
        )


class LocalCrateSourceAcquirer:
    """Materializes a CrateSource into the crate working directory."""

    def acquire(self, source: CrateSource, destination_root: Path) -> SourceAcquisitionResult:
        destination_root = Path(destination_root)
        destination_root.mkdir(parents=True, exist_ok=True)

        if source.type == CrateSourceKind.DIRECTORY:
            return self._acquire_directory(source, destination_root)
        if source.type == CrateSourceKind.ZIP:
            return self._acquire_zip(source, destination_root)
        if source.type == CrateSourceKind.URL:
            return self._acquire_url(source, destination_root)
        raise UnsupportedSourceError(f"Unsupported crate source type: {source.type}")

    def _acquire_directory(self, source: CrateSource, destination_root: Path) -> SourceAcquisitionResult:
        source_root = Path(source.value)
        try:
            shutil.copytree(source_root, destination_root, dirs_exist_ok=True)
        except OSError as exc:
            raise SourceAcquisitionError(f"Could not copy crate directory: {exc}") from exc
        return SourceAcquisitionResult(
            source=source, source_root=source_root, prepared_root=destination_root, copied=True,
        )

    def _acquire_zip(self, source: CrateSource, destination_root: Path) -> SourceAcquisitionResult:
        source_root = Path(source.value)
        try:
            with zipfile.ZipFile(source_root) as archive:
                archive.extractall(destination_root)
        except (OSError, zipfile.BadZipFile) as exc:
            raise SourceAcquisitionError(f"Could not extract crate archive: {exc}") from exc
        return SourceAcquisitionResult(
            source=source, source_root=source_root, prepared_root=destination_root, extracted=True,
        )

    def _acquire_url(self, source: CrateSource, destination_root: Path) -> SourceAcquisitionResult:
        try:
            request = Request(source.value, headers=BROWSER_HEADERS, method="GET")
            with urlopen(request, timeout=30) as response:
                with NamedTemporaryFile(delete=False, suffix=".zip") as temp_file:
                    shutil.copyfileobj(response, temp_file)
                    download_path = Path(temp_file.name)
        except (URLError, OSError, HTTPError) as exc:
            raise SourceAcquisitionError(f"Could not download crate source: {exc}") from exc
    
        try:
            if zipfile.is_zipfile(download_path):
                with zipfile.ZipFile(download_path) as archive:
                    archive.extractall(destination_root)
                extracted = True
            else:
                target_name = Path(source.value).name or "downloaded_crate"
                shutil.copy2(download_path, destination_root / target_name)
                extracted = False
        finally:
            if download_path.exists():
                download_path.unlink(missing_ok=True)
    
        return SourceAcquisitionResult(
            source=source,
            source_root=Path(source.value),
            prepared_root=destination_root,
            downloaded=True,
            extracted=extracted,
        )


# --------------------------------------------------------------------------- #
# Metadata parser / normalizer adapters
# --------------------------------------------------------------------------- #


class CrateMetadataParser:
    """Locates and loads either ro-crate-metadata.json or ro-crate-info.yaml."""

    def parse(self, request: MetadataParseRequest) -> MetadataDocument:
        root = Path(request.source.location)
        if not root.exists():
            raise MetadataParseError(f"Crate root does not exist: {root}")

        json_candidates = sorted(root.rglob("ro-crate-metadata.json"))
        yaml_candidates = sorted(root.rglob("ro-crate-info.yaml"))

        if yaml_candidates:
            path = yaml_candidates[0]
            raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
            return MetadataDocument(source=request.source, format=MetadataFormat.COMPSS_YAML, raw=raw, path=path)

        if json_candidates:
                    path = json_candidates[0]
                    raw = json.loads(path.read_text(encoding="utf-8"))
                    return MetadataDocument(source=request.source, format=MetadataFormat.RO_CRATE_JSON, raw=raw, path=path)

        raise MetadataParseError(
            f"No ro-crate-metadata.json or ro-crate-info.yaml found under {root}"
        )


class CrateMetadataNormalizer:
    """Turns a parsed MetadataDocument into domain models."""

    def normalize(self, document: MetadataDocument) -> MetadataNormalizationResult:
        if document.format == MetadataFormat.COMPSS_YAML:
            return self._normalize_compss_yaml(document)
        if document.format == MetadataFormat.RO_CRATE_JSON:
            return self._normalize_ro_crate_json(document)
        return MetadataNormalizationResult(
            document=document,
            warnings=(f"Unsupported metadata format: {document.format}",),
        )

    def _normalize_compss_yaml(self, document: MetadataDocument) -> MetadataNormalizationResult:
        raw = document.raw
        workflow_info = raw.get("COMPSs Workflow Information") or {}
        authors_raw = raw.get("Authors") or []
        participant_raw = raw.get("Participant") or {}
    
        warnings: list[str] = []
        placeholder_names = {"", "Name of your COMPSs application"}
    
        name = str(workflow_info.get("name") or "").strip()
        if name in placeholder_names:
            warnings.append("Workflow name is missing or still the template placeholder")
            name = name or "unnamed-workflow"
    
        authors = self._participants(authors_raw, role="author")
        participant = self._participant(participant_raw, role="participant")
    
        metadata = WorkflowMetadata(
            name=name,
            description=str(workflow_info.get("description") or ""),
            authors=authors,
            participant=participant,
            license=workflow_info.get("license"),
            data_persistence=self._parse_data_persistence(workflow_info.get("data_persistence")),
            source_metadata_path=document.path,
        )
    
        sources_raw = workflow_info.get("sources") or []
        sources = tuple(
            WorkflowArtifact(
                type=ArtifactKind.SOURCE,
                name=Path(str(item)).name,
                path=str(item),
            )
            for item in sources_raw
            if str(item).strip()
        )
        index = CrateIndex(sources=sources)
    
        crate_root = document.path.parent if document.path else Path(document.source.location)
        crate = CrateSummary(
            source=CrateSource(type=CrateSourceKind.DIRECTORY, value=str(crate_root)),
            location=CrateLocation(original_path=crate_root, working_path=crate_root),
            metadata=metadata,
            index=index,
        )
    
        return MetadataNormalizationResult(
            document=document,
            metadata=metadata,
            index=index,
            crate=crate,
            warnings=tuple(warnings),
        )

    def _normalize_ro_crate_json(self, document: MetadataDocument) -> MetadataNormalizationResult:
        graph = document.raw.get("@graph") or []
        root_entity_id = None
        for entity in graph:
            if entity.get("@id") == "ro-crate-metadata.json":
                root_entity_id = (entity.get("about") or {}).get("@id")
                break
        root_entity = next((e for e in graph if e.get("@id") == root_entity_id), {})

        metadata = WorkflowMetadata(
            name=root_entity.get("name") or "unnamed-workflow",
            description=root_entity.get("description", ""),
            source_metadata_path=document.path,
        )
        crate_root = document.path.parent if document.path else Path(document.source.location)
        crate = CrateSummary(
            source=CrateSource(type=CrateSourceKind.DIRECTORY, value=str(crate_root)),
            location=CrateLocation(original_path=crate_root, working_path=crate_root),
            metadata=metadata,
        )
        return MetadataNormalizationResult(
            document=document,
            metadata=metadata,
            crate=crate,
            warnings=("RO-Crate JSON parsing is minimal in this MVP: only name/description are read",),
        )

    def _participants(self, raw: object, role: str) -> tuple[WorkflowParticipant, ...]:
        if isinstance(raw, list):
            entries = raw
        elif isinstance(raw, dict):
            entries = [raw]
        else:
            return ()

        participants: list[WorkflowParticipant] = []
        for entry in entries:
            participant = self._participant(entry, role=role)
            if participant is not None:
                participants.append(participant)
        return tuple(participants)


    def _participant(self, raw: object, role: str) -> WorkflowParticipant | None:
        if not isinstance(raw, dict):
            return None

        name = str(raw.get("name") or "").strip()
        if not name:
            return None

        return WorkflowParticipant(
            name=name,
            role=role,
            email=raw.get("e-mail") or raw.get("email") or None,
            organization_name=raw.get("organisation_name") or raw.get("organization_name") or None,
            orcid=raw.get("orcid") or None,
            ror=raw.get("ror") or None,
        )

    def _parse_data_persistence(self, value: object) -> DataPersistenceKind:
        if isinstance(value, bool):
            return DataPersistenceKind.TRUE if value else DataPersistenceKind.FALSE
        text = str(value).strip().lower() if value is not None else ""
        if text in {"true", "yes"}:
            return DataPersistenceKind.TRUE
        if text in {"false", "no"}:
            return DataPersistenceKind.FALSE
        return DataPersistenceKind.UNKNOWN


# --------------------------------------------------------------------------- #
# Execution adapters
# --------------------------------------------------------------------------- #


class ShutilExecutionBackendDetector:
    """Detects SLURM vs local execution."""

    _SLURM_ENV_KEYS = (
        "SLURM_JOB_ID",
        "SLURM_CLUSTER_NAME",
        "SLURM_SUBMIT_DIR",
        "SLURM_NTASKS",
        "SLURM_JOB_NODELIST",
    )

    def detect(self) -> ExecutionBackend:
        # Only treat as SLURM when actually inside a SLURM environment
        if any(os.getenv(key) for key in self._SLURM_ENV_KEYS):
            return ExecutionBackend.SLURM
        return ExecutionBackend.LOCAL


class SubprocessExecutionParticipant:
    """Runs the built COMPSs command as a local subprocess."""

    def submit(self, submission: ExecutionSubmission) -> ExecutionOutcome:
        submission.workspace_directory.mkdir(parents=True, exist_ok=True)
        submission.log_directory.mkdir(parents=True, exist_ok=True)
        submission.results_directory.mkdir(parents=True, exist_ok=True)

        stdout_path = submission.log_directory / "log.out"
        stderr_path = submission.log_directory / "log.err"
        started_at = datetime.now(timezone.utc)

        return_code: int | None
        error_message: str | None = None
        try:
            with open(stdout_path, "w", encoding="utf-8") as stdout_file, \
                 open(stderr_path, "w", encoding="utf-8") as stderr_file:
                completed = subprocess.run(
                    submission.command.as_list(),
                    cwd=str(submission.command.working_directory or submission.execution_directory or submission.workspace_directory),
                    stdout=stdout_file,
                    stderr=stderr_file,
                    check=False,
                )
            try:
                self.move_generated_provenance_crate(
                    workspace_directory=submission.workspace_directory,
                    results_directory=submission.results_directory,
                    execution_directory=submission.results_directory,
                )
            except OSError as exc:
                if error_message:
                    error_message = f"{error_message}; could not move provenance crate(s): {exc}"
                else:
                    error_message = f"Could not move provenance crate(s): {exc}"
            return_code = completed.returncode
            status = ExecutionStatus.SUCCEEDED if return_code == 0 else ExecutionStatus.FAILED
            if return_code != 0:
                error_message = f"Process exited with code {return_code}"
        except FileNotFoundError as exc:
            return_code = None
            status = ExecutionStatus.FAILED
            error_message = f"Executable not found: {exc.filename or submission.command.executable}"
        except OSError as exc:
            return_code = None
            status = ExecutionStatus.FAILED
            error_message = str(exc)

        finished_at = datetime.now(timezone.utc)
        context = ExecutionContext(
            backend=submission.backend,
            workspace_directory=submission.workspace_directory,
            log_directory=submission.log_directory,
            results_directory=submission.results_directory,
        )
        log = ExecutionLog(stdout_path=stdout_path, stderr_path=stderr_path)
        result = ExecutionResult(
            status=status,
            command=submission.command,
            context=context,
            log=log,
            return_code=return_code,
            started_at=started_at,
            finished_at=finished_at,
            summary_message="Execution succeeded" if status == ExecutionStatus.SUCCEEDED else "Execution failed",
            error_message=error_message,
        )
        return ExecutionOutcome(result=result, submission=submission)

    def move_generated_provenance_crate(
            self,
            workspace_directory: Path,
            results_directory: Path,
            execution_directory: Path | None = None
            ) -> list[str]:
        moved: list[str] = []

        results_directory.mkdir(parents=True, exist_ok=True)
        resolved_results = results_directory.resolve()

        search_roots: list[Path] = []
        if execution_directory is not None:
            search_roots.append(execution_directory)
        search_roots.append(workspace_directory)

        seen_roots: set[str] = set()
        seen_candidates: set[str] = set()
        for root in search_roots:
            if not root.exists():
                continue

            root_key = str(root.resolve())
            if root_key in seen_roots:
                continue
            seen_roots.add(root_key)

            for candidate in root.rglob("COMPSs_RO-Crate*"):
                if not (candidate.is_dir() or candidate.is_file()):
                    continue

                candidate_resolved = candidate.resolve()
                candidate_key = str(candidate_resolved)
                if candidate_key in seen_candidates:
                    continue
                seen_candidates.add(candidate_key)

                # Ja està dins Result: no cal moure, però ho comptem.
                if candidate_resolved.is_relative_to(resolved_results):
                    moved.append(candidate.name)
                    continue

                destination = results_directory / candidate.name
                if destination.exists():
                    suffix = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
                    destination = results_directory / f"{candidate.name}_{suffix}"

                shutil.move(str(candidate), str(destination))
                moved.append(destination.name)

        return moved


__all__ = [
    "LocalFileSystem",
    "LocalCrateSourceResolver",
    "LocalCrateSourceValidator",
    "LocalCrateSourceAcquirer",
    "CrateMetadataParser",
    "CrateMetadataNormalizer",
    "ShutilExecutionBackendDetector",
    "SubprocessExecutionParticipant",
]