from __future__ import annotations

from dataclasses import dataclass, replace
from enum import Enum

import yaml
from pathlib import Path
from services.import_crate import ImportCrateResult

from infrastructure.filesystem import LocalFileSystem
from infrastructure.pycompss_inspect import LocalPyCompssMetadataInspector
from services.import_crate import ImportCrateResult, DataPersistenceKind
from models.crate import EntityKind, WorkflowEntity, WorkflowEntitySummary
from typing import Any

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
        str(item.id).startswith("dataset/")
        for item in has_part
    )

    return (DataPersistenceKind.TRUE if has_dataset_refs else DataPersistenceKind.FALSE)

def verify_rocrate(inspect_crate_result: InspectCrateResult, file_system: LocalFileSystem) -> InspectCrateResult:

    import_crate_result = inspect_crate_result.import_crate_result
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
            entity_path = import_crate_result.crate_location / entity_name
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
    elif "File" in entity_type and entity_name.startswith("dataset/"):
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
