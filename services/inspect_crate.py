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

from dataclasses import dataclass, replace
from enum import Enum

from questionary import form
import yaml
from pathlib import Path
from services.import_crate import ImportCrateResult

from infrastructure.filesystem import LocalFileSystem
from infrastructure.pycompss_inspect import LocalPyCompssMetadataInspector
from services.import_crate import ImportCrateResult, DataPersistenceKind
from models.crate import EntityKind, WorkflowEntity, WorkflowEntitySummary
from typing import Any
from urllib.parse import urlparse, unquote
import subprocess
import shlex

class InspectCrateStatus(str, Enum):
    SUCCEEDED = "succeeded"
    FAILED = "failed"


@dataclass(frozen=True, slots=True)
class InspectCrateResult:
    status: InspectCrateStatus
    import_crate_result: ImportCrateResult | None = None
    warnings: tuple[str, ...] = ()
    notes: tuple[str, ...] = ()
    inspect_output: str | None = None

def inspect_rocrate(import_crate_result: ImportCrateResult) -> InspectCrateResult:
    warnings: list[str] = []
    inspect_output: str | None = None

    inspector = LocalPyCompssMetadataInspector()

    if inspector is not None:
        ok, inspect_output, error = inspector.inspect(import_crate_result.crate_location)
        if not ok and error:
            warnings.append(error)

    updated_crate = replace(
        import_crate_result,
        data_persistence=infer_data_persistence(import_crate_result),
    )

    return InspectCrateResult(
        status=InspectCrateStatus.SUCCEEDED,
        import_crate_result=updated_crate,
        warnings=tuple(warnings),
        notes=("Crate inspection completed",),
        inspect_output=inspect_output,
    )

def get_workflow_entities(import_crate_result: ImportCrateResult) -> list[Any] | None:
    if import_crate_result.rocrate is None:
        return None
    
    has_part = import_crate_result.rocrate.root_dataset.get("hasPart", [])
    return has_part

def infer_data_persistence(import_crate_result: ImportCrateResult,) -> DataPersistenceKind:
    if import_crate_result.rocrate is None:
        return DataPersistenceKind.UNKNOWN

    has_part = get_workflow_entities(import_crate_result) or []

    has_dataset_refs = any(
        str(item.id).startswith("dataset/") or 
        str(item.id).startswith("datasets/") or
        str(item.id).startswith("data/")
        for item in has_part
    )

    return (DataPersistenceKind.TRUE if has_dataset_refs else DataPersistenceKind.FALSE)


def action_asset_ids(import_crate_result: ImportCrateResult) -> tuple[set[str], set[str]]:
    input_ids: set[str] = set()
    output_ids: set[str] = set()

    if import_crate_result.rocrate is None:
        return input_ids, output_ids

    for entity in import_crate_result.rocrate.get_entities():
        raw_type = entity.get("@type", [])
        entity_types = {raw_type} if isinstance(raw_type, str) else set(raw_type or [])

        if "CreateAction" not in entity_types:
            continue

        input_ids.update(reference_ids(entity.get("object")))
        output_ids.update(reference_ids(entity.get("result")))

    return input_ids, output_ids


def reference_ids(value: Any) -> set[str]:
    if value is None:
        return set()

    values = value if isinstance(value, list) else [value]
    identifiers: set[str] = set()

    for item in values:
        if isinstance(item, dict) and item.get("@id"):
            identifiers.add(str(item["@id"]))
        elif getattr(item, "id", None):
            identifiers.add(str(item.id))

    return identifiers


def dataset_path_for( entity_id: str, crate_root: Path, input_ids: set[str], output_ids: set[str]) -> Path | None:
    parsed = urlparse(entity_id)

    if parsed.scheme != "file" or not parsed.netloc or not parsed.path:
        return None

    remote_path = Path(unquote(parsed.path))

    if "config" in remote_path.parts:
        category = "config"
    elif entity_id in output_ids:
        category = "output"
    elif entity_id in input_ids:
        category = "input"
    else:
        return None

    return crate_root / "datasets" / category / remote_path.name


def copy_remote_file(remote_id: str, destination: Path) -> bool:
    parsed = urlparse(remote_id)
    host = parsed.netloc
    remote_path = unquote(parsed.path)

    destination.parent.mkdir(parents=True, exist_ok=True)

    scp_result = subprocess.run(
        ["scp", f"{host}:{remote_path}", str(destination)],
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )
    if scp_result.returncode == 0:
        return True

    with destination.open("wb") as output_file:
        ssh_result = subprocess.run(
            ["ssh", host, f"cat -- {shlex.quote(remote_path)}"],
            stdout=output_file,
            stderr=subprocess.PIPE,
            timeout=60,
            check=False,
        )

    if ssh_result.returncode == 0:
        return True

    destination.unlink(missing_ok=True)
    return False


def materialize_external_assets(import_crate_result: ImportCrateResult) -> dict[str, Path]:
    input_ids, output_ids = action_asset_ids(import_crate_result)
    resolved_paths: dict[str, Path] = {}

    for entity_id in input_ids | output_ids:
        destination = dataset_path_for(
            entity_id,
            import_crate_result.crate_location,
            input_ids,
            output_ids,
        )
        if destination is None:
            continue

        if destination.is_file() or copy_remote_file(entity_id, destination):
            resolved_paths[entity_id] = destination

    return resolved_paths


def verify_rocrate(inspect_crate_result: InspectCrateResult, file_system: LocalFileSystem) -> InspectCrateResult:

    import_crate_result = inspect_crate_result.import_crate_result
    resolved_paths = materialize_external_assets(import_crate_result)
    has_part = get_workflow_entities(import_crate_result)

    required_missing = {
        EntityKind.SOFTWARE_SOURCE_CODE,
        EntityKind.INPUT_OR_OUTPUT,
    }
    
    if has_part:
        entities = []
        total = 0
        total_success = 0
        total_failed = 0
        total_warnings = 0
        
        for item in has_part:
            total += 1

            entity_kind = check_type_of_entity(item, import_crate_result.crate_location)
            entity_name = item.id
            entity_path = resolved_paths.get(entity_name,import_crate_result.crate_location / entity_name)
            declared_size_bytes = item.get("contentSize")

            try:
                exists = file_system.exists(entity_path)
                entity_size = (file_system.get_size(entity_path) if exists else None )
            except OSError:
                exists = False
                entity_size = None

            if (exists and entity_size is not None and declared_size_bytes is not None):
                size_matches = entity_size == declared_size_bytes
            else:
                size_matches = None

            if not exists:
                size_matches = False

                if entity_kind in required_missing:
                    total_failed += 1
                else:
                    total_warnings += 1

            elif declared_size_bytes is None:
                total_warnings += 1

            elif entity_size is None:
                total_warnings += 1

            elif size_matches:
                total_success += 1

            else:
                total_failed += 1

            entities.append(
                WorkflowEntity(
                    type=entity_kind,
                    name=entity_name,
                    path=str(entity_path),
                    exists=exists,
                    size_bytes=entity_size,
                    declared_size_bytes=declared_size_bytes,
                    size_matches=size_matches,
                )
            )
        
        entity_summary = WorkflowEntitySummary(total=total,total_success=total_success,total_failed=total_failed,total_warnings=total_warnings,entities=entities)

        workflow_metadata = inspect_crate_result.import_crate_result.workflow_metadata
        if workflow_metadata:
            updated_workflow_metadata = replace(workflow_metadata, workflow_entity_summary=entity_summary)
            updated_import_crate_result = replace(
                inspect_crate_result.import_crate_result,
                workflow_metadata=updated_workflow_metadata,
            )
            inspect_crate_result = replace(
                inspect_crate_result,
                import_crate_result=updated_import_crate_result,
            )

    return inspect_crate_result

def check_type_of_entity(item: dict, crate_location: Path) -> EntityKind:
    entity_type = item.type
    entity_name = item.id
    if "SoftwareSourceCode" in entity_type:
        return EntityKind.SOFTWARE_SOURCE_CODE
    elif "ImageObject" in entity_type:
        return EntityKind.IMAGE_OBJECT
    elif "File" in entity_type and (entity_name.startswith("dataset/") or entity_name.startswith("datasets/") or entity_name.startswith("data/")):
        return EntityKind.INPUT_OR_OUTPUT
    elif "File" in entity_type and entity_name.endswith(".out"):
        return EntityKind.WORKERS_OUTPUT
    elif "File" in entity_type and entity_name.endswith(".err"):
        return EntityKind.WORKERS_ERROR
    elif entity_name.endswith("README"):
        return EntityKind.README
    elif entity_name.startswith("compss_submission_command_line"):
        return EntityKind.COMPSS_SUBMISSION_COMMAND_LINE_FILE
    elif is_compss_workflow_info_yaml(crate_location / entity_name):
        return EntityKind.COMPSS_WORKFLOW_YAML_FILE
    elif entity_name.endswith(".yaml") or entity_name.endswith(".yml"):
        if not is_compss_workflow_info_yaml(crate_location / entity_name):
            return EntityKind.WORKFLOW_CONFIGURATION_YAML_FILE
    else:
        return EntityKind.UNKNOWN


def is_compss_workflow_info_yaml(path: Path) -> bool:
    path = Path(path)

    if not path.is_file() or path.suffix.lower() not in {".yaml", ".yml"}:
        return False

    try:
        document = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, yaml.YAMLError):
        return False

    return (isinstance(document, dict) and isinstance(document.get("COMPSs Workflow Information"), dict))
