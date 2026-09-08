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

"""Use case for creating COMPSs provenance configuration."""

from __future__ import annotations
from dataclasses import dataclass

from pathlib import Path
from typing import Protocol

import yaml

from application.ports.file_system import FileSystemOperationResult
from application.use_cases.import_crate import (
    DataPersistenceKind,
    ImportCrateResult,
)
from domain.errors import FileSystemError, ValidationError
from domain.models.crate import WorkflowParticipant


class WritableFileSystem(Protocol):
    def write_text(self, path: Path, content: str, encoding: str = "utf-8") -> FileSystemOperationResult:
        ...


@dataclass(frozen=True, slots=True)
class PrepareProvenanceRequest:
    crate: ImportCrateResult
    filesystem: WritableFileSystem
    provenance_root: Path
    participant_name: str | None = None
    participant_email: str | None = None
    participant_organization: str | None = None
    participant_orcid: str | None = None
    participant_ror: str | None = None
    data_persistence_kind: DataPersistenceKind | None = None

    def __post_init__(self) -> None:
        if not str(self.provenance_root).strip():
            raise ValueError("provenance_root cannot be empty")


@dataclass(frozen=True, slots=True)
class PrepareProvenanceResult:
    provenance_config_file: Path | None = None
    warnings: tuple[str, ...] = ()
    notes: tuple[str, ...] = ()


class DefaultPrepareProvenanceService:
    """Writes the configuration used by COMPSs to generate provenance."""

    def execute(self, request: PrepareProvenanceRequest) -> PrepareProvenanceResult:
        workflow_metadata = request.crate.workflow_metadata
        if workflow_metadata is None:
            raise ValidationError(
                "Cannot prepare provenance without workflow metadata"
            )

        agent = build_agent(request, workflow_metadata.authors)
        sources = source_paths(request.crate)

        if not sources:
            return PrepareProvenanceResult(warnings=("No workflow source files were found; provenance configuration was not written.",),)

        workflow_information: dict[str, object] = {
            "name": workflow_metadata.name,
            "sources": sources,
        }
        
        if workflow_metadata.description:
            workflow_information["description"] = workflow_metadata.description
        
        if workflow_metadata.license:
            workflow_information["license"] = workflow_metadata.license

        workflow_information["data_persistence"] = request.data_persistence
        
        document = {
            "COMPSs Workflow Information": workflow_information,
            "Authors": [
                participant_document(author)
                for author in workflow_metadata.authors
            ],
            "Agent": participant_document(agent),
        }

        output_file = Path(request.provenance_root) / "ro-crate-info.yaml"
        content = yaml.safe_dump(
            document,
            allow_unicode=False,
            default_flow_style=False,
            sort_keys=False,
        )

        write_result = request.filesystem.write_text(output_file, content)
        if not write_result.succeeded:
            raise FileSystemError(
                "Could not write provenance configuration",
                details=write_result.message or str(output_file),
            )

        return PrepareProvenanceResult(
            provenance_config_file=output_file,
            notes=("Provenance configuration prepared",),
        )


def build_agent(request: PrepareProvenanceRequest, authors: tuple[WorkflowParticipant, ...] ) -> WorkflowParticipant:
    first_author_name = authors[0].name if authors else None

    name = first_non_empty(request.participant_name, first_author_name) or "Unknown participant"

    return WorkflowParticipant(
        name=name,
        role="Agent",
        email=first_non_empty(request.participant_email),
        organization_name=first_non_empty(request.participant_organization),
        orcid=first_non_empty(request.participant_orcid),
        ror=first_non_empty(request.participant_ror),
    )


def source_paths(crate: ImportCrateResult) -> list[str]:
    if crate.rocrate is None:
        return []

    sources: list[str] = []

    for reference in crate.rocrate.root_dataset.get("hasPart", []):
        entity = reference

        if isinstance(reference, dict):
            entity_id = reference.get("@id")
            if not entity_id:
                continue
            entity = crate.rocrate.get_entity(entity_id)

        if entity is None:
            continue

        raw_type = entity.get("@type", [])
        entity_types = (
            {raw_type}
            if isinstance(raw_type, str)
            else set(raw_type or [])
        )

        if "SoftwareSourceCode" not in entity_types:
            continue

        entity_id = getattr(entity, "id", None)
        if not entity_id:
            continue

        source_path = crate.crate_location / entity_id

        if source_path.exists():
            sources.append(str(source_path.resolve()))

    return sources

def participant_document(participant: WorkflowParticipant) -> dict[str, str]:
    document: dict[str, str] = {"name": str(participant.name)}

    if participant.email:
        document["e-mail"] = str(participant.email)

    if participant.orcid:
        document["orcid"] = str(participant.orcid)

    if participant.organization_name:
        document["organisation_name"] = str(
            participant.organization_name
        )

    if participant.ror:
        document["ror"] = str(participant.ror)

    return document

def first_non_empty(*values: str | None) -> str | None:
    for value in values:
        if value is not None and value.strip():
            return value.strip()
    return None
