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
from typing import Any, Protocol, runtime_checkable

import yaml

from application.ports.file_system import DirectoryCreateRequest, FileSystemManager
from application.ports.metadata_parser import MetadataDocument, MetadataNormalizationResult
from domain.errors import FileSystemError, MetadataError, ValidationError
from domain.models.crate import CrateSummary, WorkflowMetadata, WorkflowParticipant
from domain.models.crate import CrateSummary, DataPersistenceKind, WorkflowMetadata, WorkflowParticipant

class PrepareProvenanceStatus(str, Enum):
    PENDING = "pending"
    VALIDATED = "validated"
    PREPARED = "prepared"
    PUBLISHED = "published"
    FAILED = "failed"


@dataclass(frozen=True, slots=True)
class PrepareProvenanceRequest:
    crate: CrateSummary
    provenance_root: Path
    participant_name: str
    participant_email: str | None = None
    participant_organization: str | None = None
    participant_orcid: str | None = None
    participant_ror: str | None = None
    write_metadata_file: bool = True
    preserve_existing_metadata: bool = True
    overwrite_existing: bool = False

    def __post_init__(self) -> None:
        if self.crate is None:
            raise ValidationError("PrepareProvenanceRequest.crate cannot be None")
        if not str(self.provenance_root).strip():
            raise ValidationError("PrepareProvenanceRequest.provenance_root cannot be empty")
        if not self.participant_name.strip():
            raise ValidationError("PrepareProvenanceRequest.participant_name cannot be empty")


@dataclass(frozen=True, slots=True)
class PrepareProvenancePlan:
    request: PrepareProvenanceRequest
    provenance_root: Path
    metadata_path: Path | None = None
    output_path: Path | None = None
    existing_metadata: WorkflowMetadata | None = None
    participant: WorkflowParticipant | None = None
    target_metadata_path: Path | None = None

    def __post_init__(self) -> None:
        if not str(self.provenance_root).strip():
            raise ValidationError("PrepareProvenancePlan.provenance_root cannot be empty")


@dataclass(frozen=True, slots=True)
class PrepareProvenanceResult:
    status: PrepareProvenanceStatus
    request: PrepareProvenanceRequest
    plan: PrepareProvenancePlan
    metadata_document: MetadataDocument | None = None
    normalization: MetadataNormalizationResult | None = None
    updated_metadata: WorkflowMetadata | None = None
    created_metadata_file: Path | None = None
    warnings: tuple[str, ...] = ()
    notes: tuple[str, ...] = ()
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    @property
    def prepared(self) -> bool:
        return self.status in {PrepareProvenanceStatus.PREPARED, PrepareProvenanceStatus.PUBLISHED}

    @property
    def published(self) -> bool:
        return self.status == PrepareProvenanceStatus.PUBLISHED

    @property
    def has_warnings(self) -> bool:
        return len(self.warnings) > 0

    @property
    def has_notes(self) -> bool:
        return len(self.notes) > 0


@runtime_checkable
class PrepareProvenanceUseCase(Protocol):
    def execute(self, request: PrepareProvenanceRequest) -> PrepareProvenanceResult:
        """
        Prepare provenance metadata for a crate run.
        """
        ...


@runtime_checkable
class PrepareProvenancePlanner(Protocol):
    def build_plan(self, request: PrepareProvenanceRequest) -> PrepareProvenancePlan:
        """
        Build the provenance preparation plan.
        """
        ...


@runtime_checkable
class ProvenanceWriter(Protocol):
    def write(self, plan: PrepareProvenancePlan, metadata: WorkflowMetadata) -> Path:
        """
        Persist provenance metadata and return the output path.
        """
        ...


class PrepareProvenancePortError(FileSystemError):
    pass


class PrepareProvenanceMetadataError(MetadataError):
    pass


class PrepareProvenanceFailure(PrepareProvenancePortError):
    def __init__(self, message: str, details: str | None = None):
        super().__init__(message=message, details=details, recoverable=False)


class DefaultPrepareProvenanceService:
    def __init__(self, file_system: FileSystemManager) -> None:
        self._file_system = file_system

    def build_plan(self, request: PrepareProvenanceRequest) -> PrepareProvenancePlan:
        provenance_root = request.provenance_root
        metadata_path = request.crate.location.working_path or request.crate.location.original_path
        if metadata_path is None:
            raise PrepareProvenanceFailure(
                "Could not determine crate metadata location",
                details="crate location does not provide a usable path",
            )

        participant = WorkflowParticipant(
            role="participant",
            name=request.participant_name,
            email=request.participant_email,
            organization_name=request.participant_organization,
            orcid=request.participant_orcid,
            ror=request.participant_ror,
        )

        target_metadata_path = provenance_root / "ro-crate-info.yaml"
        return PrepareProvenancePlan(
            request=request,
            provenance_root=provenance_root,
            metadata_path=metadata_path,
            participant=participant,
            target_metadata_path=target_metadata_path,
        )

    def execute(self, request: PrepareProvenanceRequest) -> PrepareProvenanceResult:
        plan = self.build_plan(request)
        warnings: list[str] = []
        notes: list[str] = []

        if request.write_metadata_file and plan.target_metadata_path is not None:
            if self._file_system.exists(plan.target_metadata_path) and not request.overwrite_existing:
                raise PrepareProvenanceFailure(
                    f"Provenance metadata already exists: {plan.target_metadata_path}",
                    details="set overwrite_existing=True to replace the file",
                )

            updated_metadata = self._build_updated_metadata(request, plan)
            created_path = self._write_metadata_file(plan.target_metadata_path, updated_metadata, request)
            status = PrepareProvenanceStatus.PUBLISHED
            return PrepareProvenanceResult(
                status=status,
                request=request,
                plan=plan,
                updated_metadata=updated_metadata,
                created_metadata_file=created_path,
                warnings=tuple(dict.fromkeys(warnings)),
                notes=tuple(dict.fromkeys(notes)),
            )

        updated_metadata = self._build_updated_metadata(request, plan)
        return PrepareProvenanceResult(
            status=PrepareProvenanceStatus.PREPARED,
            request=request,
            plan=plan,
            updated_metadata=updated_metadata,
            warnings=tuple(dict.fromkeys(warnings)),
            notes=tuple(dict.fromkeys(notes)),
        )

    def _build_updated_metadata(
        self,
        request: PrepareProvenanceRequest,
        plan: PrepareProvenancePlan,
    ) -> WorkflowMetadata:
        existing = request.crate.metadata

        participant = WorkflowParticipant(
            role="participant",
            name=request.participant_name,
            email=request.participant_email,
            organization_name=request.participant_organization,
            orcid=request.participant_orcid,
            ror=request.participant_ror,
        )

        authors = existing.authors
        if request.preserve_existing_metadata and existing.participant is not None:
            notes = list()
            notes.append("Existing participant metadata was preserved in the domain model")
            _ = notes

        return WorkflowMetadata(
            name=existing.name,
            description=existing.description,
            version=existing.version,
            authors=authors,
            participant=participant,
            license=existing.license,
            created_at=existing.created_at,
            generated_at=datetime.now(timezone.utc),
            crate_version=existing.crate_version,
            compss_version=existing.compss_version,
            data_persistence=existing.data_persistence,
            source_metadata_path=existing.source_metadata_path,
        )

    def _write_metadata_file(
        self,
        target_path: Path,
        metadata: WorkflowMetadata,
        request: PrepareProvenanceRequest,
    ) -> Path:
        if not self._file_system.exists(target_path.parent):
            self._file_system.create_directory(
                DirectoryCreateRequest(path=target_path.parent, parents=True, exist_ok=True)
            )

        content = render_ro_crate_info_yaml(metadata, request.crate)
        write_result = self._file_system.write_text(target_path, content)
        if not write_result.succeeded:
            raise PrepareProvenanceFailure(
                f"Could not write provenance metadata: {target_path}",
                details=write_result.message,
            )
        return target_path


def _participant_to_dict(participant: WorkflowParticipant) -> dict[str, Any]:
    return {
        "name": participant.name,
        # "e-mail": participant.email or "",
        # "orcid": participant.orcid or "",
        # "organisation_name": participant.organization_name or "",
        # "ror": participant.ror or "",
    }


def _load_base_ro_crate_info(metadata: WorkflowMetadata) -> dict[str, Any] | None:
    path = metadata.source_metadata_path
    if path is None or path.name != "ro-crate-info.yaml" or not path.is_file():
        return None

    raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    return raw if isinstance(raw, dict) else None


def _render_fallback_ro_crate_info_yaml(metadata: WorkflowMetadata, crate: CrateSummary) -> str:
    sources = [artifact.path for artifact in crate.index.sources]

    document: dict[str, Any] = {
        "COMPSs Workflow Information": {
            "name": metadata.name,
            "description": metadata.description,
            "sources": sources,
            "data_persistence": metadata.data_persistence == DataPersistenceKind.TRUE,
        },
        "Authors": [_participant_to_dict(author) for author in metadata.authors],
        "Participant": _participant_to_dict(metadata.participant) if metadata.participant else {},
    }
    return yaml.safe_dump(document, sort_keys=False, allow_unicode=True)


def render_ro_crate_info_yaml(metadata: WorkflowMetadata, crate: CrateSummary) -> str:
    base_document = _load_base_ro_crate_info(metadata)
    if base_document is None:
        return _render_fallback_ro_crate_info_yaml(metadata, crate)

    workflow_info = base_document.get("COMPSs Workflow Information")
    if not isinstance(workflow_info, dict):
        workflow_info = {}
        base_document["COMPSs Workflow Information"] = workflow_info

    # Keep original workflow/authors data, but refresh core values if needed.
    workflow_info["name"] = metadata.name
    workflow_info["description"] = metadata.description
    workflow_info["data_persistence"] = metadata.data_persistence == DataPersistenceKind.TRUE

    if "Authors" not in base_document or not isinstance(base_document.get("Authors"), list):
        base_document["Authors"] = [_participant_to_dict(author) for author in metadata.authors]

    base_document["Participant"] = _participant_to_dict(metadata.participant) if metadata.participant else {}

    return yaml.safe_dump(base_document, sort_keys=False, allow_unicode=True)


def has_updated_metadata(result: PrepareProvenanceResult) -> bool:
    return result.updated_metadata is not None


def has_created_metadata_file(result: PrepareProvenanceResult) -> bool:
    return result.created_metadata_file is not None


__all__ = [
    "DefaultPrepareProvenanceService",
    "PrepareProvenanceFailure",
    "PrepareProvenancePlan",
    "PrepareProvenancePortError",
    "PrepareProvenanceRequest",
    "PrepareProvenanceResult",
    "PrepareProvenanceStatus",
    "PrepareProvenanceUseCase",
    "ProvenanceWriter",
    "has_created_metadata_file",
    "has_updated_metadata",
    "render_ro_crate_info_yaml",
]