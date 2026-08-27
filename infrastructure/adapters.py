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
import subprocess
import pty
from datetime import datetime, timezone
from pathlib import Path

import yaml

from application.ports.executor import ExecutionOutcome
from application.ports.file_system import (
    FileMetadata,
    FileSystemOperationResult,
)
from application.ports.metadata_parser import (
    MetadataDocument,
    MetadataFormat,
    MetadataInspectionResult,
    MetadataNormalizationResult,
    MetadataParseRequest,
)
from domain.errors import (
    MetadataParseError,
    SourceAcquisitionError,
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

# --------------------------------------------------------------------------- #
# File system adapter
# --------------------------------------------------------------------------- #


class LocalFileSystem:
    """
        The LocalFileSystem class provides an interface for managing files and directories
        on the local filesystem. It uses Python's pathlib, shutil, and os modules to perform
        common filesystem operations, such as checking whether a file or directory exists,
        writing files, creating directories, files
        and directories. It also provides methods for retrieving file metadata and manipulating
        paths. The class acts as an abstraction layer, allowing the rest of the application to
        interact with the local filesystem without directly depending on the underlying filesystem
        operations.
    """

    # verify if a path exists
    def exists(self, path: Path) -> bool:
        return Path(path).exists()

    # 
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
    
    def create_directory(self, path: Path, parents: bool, exist_ok: bool) -> FileSystemOperationResult:
        """
        Creates a directory at the specified path.

        Parameters:
            path (Path): The path of the directory to create.
            parents (bool): Whether to create parent directories if they do not exist.
            exist_ok (bool): Whether to ignore the error if the directory already exists.

        Returns:
            FileSystemOperationResult: The status of the directory creation operation.
            
            class FileSystemOperationResult:
                path: Path The path on which the operation was performed.
                succeeded: bool Whether the operation succeeded.
                message: str = "" An optional message providing additional information about the operation.
                bytes_transferred: int | None = None The number of bytes transferred during the operation, if applicable.
        """
        try:
            Path(path).mkdir(parents=parents, exist_ok=exist_ok)
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

###   do not delete
class CrateMetadataParser:
    """Locates and loads either ro-crate-metadata.json or ro-crate-info.yaml."""

    def parse(self, request: MetadataParseRequest) -> MetadataDocument:
        root = Path(request.source.location)
        if not root.exists():
            raise MetadataParseError(f"Crate root does not exist: {root}")

        json_candidates = sorted(root.rglob("ro-crate-metadata.json"))
        yaml_candidates = sorted(root.rglob("ro-crate-info.yaml"))

        if json_candidates:
            path = json_candidates[0]
            raw = json.loads(path.read_text(encoding="utf-8"))
            return MetadataDocument(source=request.source, format=MetadataFormat.RO_CRATE_JSON, raw=raw, path=path)

        if yaml_candidates:
            path = yaml_candidates[0]
            raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
            return MetadataDocument(source=request.source, format=MetadataFormat.COMPSS_YAML, raw=raw, path=path)

        raise MetadataParseError(
            f"No ro-crate-metadata.json or ro-crate-info.yaml found under {root}"
        )

## ## DO NOT DELETE
class LocalPyCompssMetadataInspector:
    """Runs pycompss inspect on the crate metadata source using a PTY so Rich keeps colors."""

    def __init__(self, executable: str = "pycompss") -> None:
        self._executable = executable

    def inspect(self, document: MetadataDocument) -> MetadataInspectionResult:
        if document.format == MetadataFormat.RO_CRATE_JSON and document.path is not None:
            target = document.path.parent
        elif document.format == MetadataFormat.COMPSS_YAML and document.path is not None:
            target = document.path
        else:
            target = Path(document.source.location)
        # if you want the verbose output
        #command = [self._executable, "inspect", "-v", str(target)]
        command = [self._executable, "inspect", str(target)]

        try:
            master_fd, slave_fd = pty.openpty()
        except OSError as exc:
            return MetadataInspectionResult(
                ok=False,
                warning=f"pycompss inspect PTY allocation failed: {exc}",
            )

        try:
            process = subprocess.Popen(
                command,
                stdin=slave_fd,
                stdout=slave_fd,
                stderr=slave_fd,
                close_fds=True,
            )
        except FileNotFoundError:
            os.close(master_fd)
            os.close(slave_fd)
            return MetadataInspectionResult(
                ok=False,
                warning="pycompss inspect unavailable: executable 'pycompss' not found",
            )
        except OSError as exc:
            os.close(master_fd)
            os.close(slave_fd)
            return MetadataInspectionResult(
                ok=False,
                warning=f"pycompss inspect could not be executed: {exc}",
            )

        os.close(slave_fd)

        chunks: list[bytes] = []
        try:
            while True:
                try:
                    data = os.read(master_fd, 4096)
                except OSError:
                    break
                if not data:
                    break
                chunks.append(data)
        finally:
            try:
                os.close(master_fd)
            except OSError:
                pass

        return_code = process.wait()
        output = b"".join(chunks).decode("utf-8", errors="replace").rstrip()

        if return_code == 0:
            return MetadataInspectionResult(
                ok=True,
                stdout=output or None,
            )

        details = output or "no diagnostic output"
        return MetadataInspectionResult(
            ok=False,
            stdout=output or None,
            warning=f"pycompss inspect failed (exit code {return_code}): {details}",
        )
    
### DO NOT DELETE
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
            data_persistence=self._infer_data_persistence(root_entity=document.raw, entities_by_id={}),  # Placeholder for data persistence inference
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
            source=CrateSource(type=CrateSourceKind.DIRECTORY, name=str(crate_root)),
            location=CrateLocation(original_path=crate_root, crate_path=crate_root),
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
        entities_by_id = {
            entity.get("@id"): entity
            for entity in graph
            if isinstance(entity, dict) and entity.get("@id")
        }

        root_entity = self._find_root_entity(graph)
        compss_entity = entities_by_id.get("#compss", {})
        compss_version = compss_entity.get("version")

        run_entity = self._find_run_entity(root_entity, entities_by_id)
        execution_site = self._extract_execution_site(run_entity)

        authors = self._resolve_authors(root_entity, entities_by_id)
        sources = self._resolve_sources(root_entity, entities_by_id)

        crate_root = document.path.parent if document.path else Path(document.source.location)

        metadata = WorkflowMetadata(
            name=str(root_entity.get("name") or "unnamed-workflow"),
            description=str(root_entity.get("description") or ""),
            license=root_entity.get("license"),
            authors=authors,
            compss_version=compss_version,
            execution_site=execution_site,
            data_persistence=self._infer_data_persistence(root_entity=root_entity, entities_by_id=entities_by_id),
            source_metadata_path=document.path,
        )

        index = CrateIndex(sources=sources)
        crate = CrateSummary(
            source=CrateSource(type=CrateSourceKind.DIRECTORY, name=str(crate_root)),
            location=CrateLocation(original_path=crate_root, crate_path=crate_root),
            metadata=metadata,
            index=index,
        )

        return MetadataNormalizationResult(
            document=document,
            metadata=metadata,
            index=index,
            crate=crate,
        )

    def _find_root_entity(self, graph: list[dict]) -> dict:
        for entity in graph:
            if entity.get("@id") == "./":
                return entity
        for entity in graph:
            if entity.get("@id") == "ro-crate-metadata.json":
                about = entity.get("about")
                if isinstance(about, dict):
                    root_id = about.get("@id")
                    if root_id:
                        return next((item for item in graph if item.get("@id") == root_id), {})
        return {}

    def _find_run_entity(self, root_entity: dict, entities_by_id: dict[str, dict]) -> dict:
        mentions = root_entity.get("mentions")
        mention_id = mentions.get("@id") if isinstance(mentions, dict) else None
        if mention_id and mention_id in entities_by_id:
            return entities_by_id[mention_id]

        for entity in entities_by_id.values():
            entity_type = entity.get("@type")
            if entity_type == "CreateAction" or (isinstance(entity_type, list) and "CreateAction" in entity_type):
                return entity
        return {}

    def _extract_execution_site(self, run_entity: dict) -> str | None:
        name = str(run_entity.get("name") or "")
        marker = " execution at "
        if marker in name:
            tail = name.split(marker, 1)[1]
            return tail.split(" with JOB_ID", 1)[0].strip() or None

        entity_id = str(run_entity.get("@id") or "")
        if "marenostrum" in entity_id:
            tail = entity_id.split("marenostrum", 1)[1]
            return "marenostrum" + tail.split("_", 1)[0]

        return None

    def _resolve_authors(self, root_entity: dict, entities_by_id: dict[str, dict]) -> tuple[WorkflowParticipant, ...]:
        creator_ids = root_entity.get("creator") or []
        if isinstance(creator_ids, dict):
            creator_ids = [creator_ids]

        authors: list[WorkflowParticipant] = []
        for creator in creator_ids:
            creator_id = creator.get("@id") if isinstance(creator, dict) else None
            if not creator_id:
                continue
            person = entities_by_id.get(creator_id, {})
            name = str(person.get("name") or "").strip()
            if not name:
                continue
            authors.append(
                WorkflowParticipant(
                    name=name,
                    role="author",
                    email=self._extract_email(person),
                    organization_name=self._extract_organization_name(person, entities_by_id),
                    orcid=creator_id if creator_id.startswith("https://orcid.org/") else None,
                )
            )
        return tuple(authors)

    def _resolve_sources(self, root_entity: dict, entities_by_id: dict[str, dict]) -> tuple[WorkflowArtifact, ...]:
        sources: list[WorkflowArtifact] = []

        main_entity = root_entity.get("mainEntity")
        main_entity_id = main_entity.get("@id") if isinstance(main_entity, dict) else None
        if main_entity_id:
            source_entity = entities_by_id.get(main_entity_id, {})
            name = str(source_entity.get("name") or Path(main_entity_id).name)
            sources.append(
                WorkflowArtifact(
                    type=ArtifactKind.SOURCE,
                    name=name,
                    path=main_entity_id,
                )
            )

        return tuple(sources)

    #  # searching for the data persistence information in the crate root directory by checking if a "dataset" directory exists. If it does, it returns DataPersistenceKind.TRUE, otherwise DataPersistenceKind.FALSE.
    # def _infer_data_persistence(self, crate_root: Path) -> DataPersistenceKind:
    #     dataset_dir = crate_root / "dataset"
    #     return DataPersistenceKind.TRUE if dataset_dir.is_dir() else DataPersistenceKind.FALSE

    def extract_ids(self,value: object) -> list[str]:
        ids: list[str] = []
        if isinstance(value, dict):
            id_value = value.get("@id")
            if isinstance(id_value, str):
                ids.append(id_value)
        elif isinstance(value, list):
            for item in value:
                ids.extend(self.extract_ids(item)) 
        return ids

    def _infer_data_persistence(self, root_entity: dict, entities_by_id: dict[str, dict]) -> DataPersistenceKind:    
        candidate_ids: list[str] = []
    
        candidate_ids.extend(self.extract_ids(root_entity.get("hasPart")))
    
        for entity in entities_by_id.values():
            if isinstance(entity, dict):
                entity_id = entity.get("@id")
                if isinstance(entity_id, str):
                    candidate_ids.append(entity_id)
    
        has_dataset_refs = any(item.startswith("dataset/") for item in candidate_ids)
        return DataPersistenceKind.TRUE if has_dataset_refs else DataPersistenceKind.FALSE

    def _extract_email(self, person: dict) -> str | None:
        contact = person.get("contactPoint")
        if isinstance(contact, dict):
            email = contact.get("email")
            if email:
                return str(email)
        return None

    def _extract_organization_name(self, person: dict,
        entities_by_id: dict[str, dict],
    ) -> str | None:
        affiliation = person.get("affiliation")
        affiliation_id = affiliation.get("@id") if isinstance(affiliation, dict) else None
        if not affiliation_id:
            return None
        org = entities_by_id.get(affiliation_id, {})
        name = str(org.get("name") or "").strip()
        return name or None

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

### DO NOT DELETE
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

        generated_ro_crate_path = self._find_generated_ro_crate_path(submission)

        return_code = completed.returncode
        status = ExecutionStatus.SUCCEEDED if return_code == 0 else ExecutionStatus.FAILED
        if return_code != 0:
            error_message = f"Process exited with code {return_code}"

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
            generated_ro_crate_path=generated_ro_crate_path,
        )
        return ExecutionOutcome(result=result, submission=submission)

    def _find_generated_ro_crate_path(self, submission: ExecutionSubmission) -> Path:
        generated_ro_crate_path = None
        for candidate in sorted(submission.results_directory.rglob("COMPSs_RO-Crate*"), key=lambda p: p.stat().st_mtime if p.exists() else 0.0, reverse=True):
            if candidate.is_dir() or candidate.is_file():
                generated_ro_crate_path = candidate.resolve()
                break
        return generated_ro_crate_path

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