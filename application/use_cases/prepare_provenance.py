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
from typing import Any

import yaml

from application.ports.metadata_parser import MetadataDocument, MetadataNormalizationResult
from domain.errors import FileSystemError, ValidationError
from domain.models.crate import WorkflowMetadata, WorkflowParticipant, DataPersistenceKind #, CrateSummary
from infrastructure.adapters import LocalFileSystem

class PrepareProvenanceStatus(str, Enum):
    PENDING = "pending"
    VALIDATED = "validated"
    PREPARED = "prepared"
    PUBLISHED = "published"


_PLACEHOLDER_SOURCES = {
    "/absolute_path_to/dir_1/",
    "relative_path_to/dir_2/",
    "main_file.py",
    "relative_path/aux_file_1.py",
    "/abs_path/aux_file_2.py",
}

_PLACEHOLDER_MAIN = {"my_main_file.py", "main_file.py", ""}


def _is_placeholder_source(value: str) -> bool:
    text = value.strip()
    return (not text) or (text in _PLACEHOLDER_SOURCES) or ("absolute_path_to" in text)

def _existing_path_from_source(source_name: str, crate_root: Path) -> Path | None:
    raw = source_name.strip()
    if not raw:
        return None
    path = Path(raw)
    candidate = path if path.is_absolute() else (crate_root / path)
    try:
        candidate = candidate.resolve()
    except OSError:
        return None
    return candidate if candidate.exists() else None


def _collect_real_sources(crate: CrateSummary) -> list[str]:
    crate_root = crate.location
    if crate_root is None:
        return []

    resolved: list[str] = []
    seen: set[str] = set()

    # Prefer declared crate sources when they exist on disk.
    for artifact in crate.index.sources:
        raw = str(artifact.path).strip()
        if _is_placeholder_source(raw):
            continue
        candidate = _existing_path_from_source(raw, crate_root)
        if candidate is None:
            continue
        normalized = str(candidate)
        if normalized not in seen:
            seen.add(normalized)
            resolved.append(normalized)
    # Fallback for common COMPSs layouts in imported crates.
    for relative in ("application_sources/src", "application_sources", "src"):
        candidate = (crate_root / relative).resolve()
        if candidate.exists():
            normalized = str(candidate)
            if normalized not in seen:
                seen.add(normalized)
                resolved.append(normalized)

    return resolved


def _sanitize_sources_main_file(workflow_info: dict[str, Any], sources: list[str]) -> None:
    current = str(workflow_info.get("sources_main_file") or "").strip()
    if current in _PLACEHOLDER_MAIN:
        workflow_info.pop("sources_main_file", None)
        return

    if not sources:
        return

    current_name = Path(current).name
    found = False
    for source in sources:
        source_path = Path(source)
        if source_path.is_file() and source_path.name == current_name:
            found = True
            break
        if source_path.is_dir() and (source_path / current_name).exists():
            found = True
            break

    if not found:
        workflow_info.pop("sources_main_file", None)


@dataclass(frozen=True, slots=True)
class PrepareProvenanceRequest:
    # crate: CrateSummary
    provenance_root: Path
    participant_name: str | None = None
    participant_email: str | None = None
    participant_organization: str | None = None
    participant_orcid: str | None = None
    participant_ror: str | None = None
    write_metadata_file: bool = True
    preserve_existing_metadata: bool = True
    overwrite_existing: bool = False

    def __post_init__(self) -> None:
        # if self.crate is None:
        #     raise ValidationError("PrepareProvenanceRequest.crate cannot be None")
        if not str(self.provenance_root).strip():
            raise ValidationError("PrepareProvenanceRequest.provenance_root cannot be empty")
        # if not self.participant_name.strip():
        #     raise ValidationError("PrepareProvenanceRequest.participant_name cannot be empty")


@dataclass(frozen=True, slots=True)
class PrepareProvenancePlan:
    request: PrepareProvenanceRequest
    provenance_root: Path
    metadata_path: Path | None = None
    output_path: Path | None = None
    existing_metadata: WorkflowMetadata | None = None
    agent: WorkflowParticipant | None = None
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
    provenance_config_file: Path | None = None
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


class PrepareProvenancePortError(FileSystemError):
    pass


class PrepareProvenanceFailure(PrepareProvenancePortError):
    def __init__(self, message: str, details: str | None = None):
        super().__init__(message=message, details=details, recoverable=False)



### do not delete
class DefaultPrepareProvenanceService:
    def __init__(self, file_system: LocalFileSystem) -> None:
        self._file_system = file_system

    def build_plan(self, request: PrepareProvenanceRequest) -> PrepareProvenancePlan:
        provenance_root = request.provenance_root
        metadata_path = request.crate.location
        if metadata_path is None:
            raise PrepareProvenanceFailure(
                "Could not determine crate metadata location",
                details="crate location does not provide a usable path",
            )

        agent = WorkflowParticipant(
            role="Agent",
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
            agent=agent,
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
                provenance_config_file=created_path,
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
        if request.preserve_existing_metadata and existing.agent is not None:
            notes = list()
            notes.append("Existing agent metadata was preserved in the domain model")
            _ = notes

        return WorkflowMetadata(
            name=existing.name,
            description=existing.description,
            version=existing.version,
            authors=authors,
            agent=participant,
            license=existing.license,
            created_at=existing.created_at,
            generated_at=datetime.now(timezone.utc),
            crate_version=existing.crate_version,
            compss_version=existing.compss_version,
            data_persistence=existing.data_persistence,
            source_metadata_path=existing.source_metadata_path,
        )

    def _write_metadata_file(self, target_path: Path, metadata: WorkflowMetadata,request: PrepareProvenanceRequest) -> Path:
        # if not self._file_system.exists(target_path.parent):
        #     self._file_system.create_directory(path=target_path.parent, parents=True, exist_ok=True)

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
    sources = _collect_real_sources(crate)

    document: dict[str, Any] = {
        "COMPSs Workflow Information": {
            "name": metadata.name,
            "description": metadata.description,
            "sources": sources,
            "data_persistence": metadata.data_persistence == DataPersistenceKind.TRUE,
        },
        "Authors": [_participant_to_dict(author) for author in metadata.authors],
        "Agent": _participant_to_dict(metadata.agent) if metadata.agent else {},
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

    if "license" not in workflow_info and metadata.license:
        workflow_info["license"] = metadata.license

    # IMPORTANT:
    # If the input ro-crate-info.yaml was a template, its sources are placeholders.
    # Replace them with real, existing paths from the imported crate.
    real_sources = _collect_real_sources(crate)
    if real_sources:
        workflow_info["sources"] = real_sources
    else:
        existing_sources = workflow_info.get("sources")
        if not isinstance(existing_sources, list):
            workflow_info["sources"] = []

    if "Authors" not in base_document or not isinstance(base_document.get("Authors"), list):
        base_document["Authors"] = [_participant_to_dict(author) for author in metadata.authors]

    base_document["Agent"] = _participant_to_dict(metadata.agent) if metadata.agent else {}
    base_document.pop("Participant", None)
    
    _sanitize_sources_main_file(workflow_info, workflow_info.get("sources") or [])
    return yaml.safe_dump(base_document, sort_keys=False, allow_unicode=True)


def has_updated_metadata(result: PrepareProvenanceResult) -> bool:
    return result.updated_metadata is not None


def has_provenance_config_file(result: PrepareProvenanceResult) -> bool:
    return result.provenance_config_file is not None


__all__ = [
    "DefaultPrepareProvenanceService",
    "PrepareProvenanceFailure",
    "PrepareProvenancePlan",
    "PrepareProvenancePortError",
    "PrepareProvenanceRequest",
    "PrepareProvenanceResult",
    "PrepareProvenanceStatus",
    "has_provenance_config_file",
    "has_updated_metadata",
    "render_ro_crate_info_yaml",
]