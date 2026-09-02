from __future__ import annotations

from dataclasses import dataclass, replace
from enum import Enum

from application.use_cases.import_crate import ImportCrateResult

from domain.models.crate import EntityKind
from infrastructure.pycompss_inspect import LocalPyCompssMetadataInspector
from application.use_cases.import_crate import ImportCrateResult, DataPersistenceKind
from domain.models.crate import WorkflowEntity, WorkflowEntitySummary

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

def _inspect_rocrate(import_crate_result: ImportCrateResult) -> InspectCrateResult:
    warnings: list[str] = []
    inspect_output: str | None = None

    inspector = LocalPyCompssMetadataInspector()

    if inspector is not None:
        ok, inspect_output, error = inspector.inspect(import_crate_result.crate_location)
        if not ok and error:
            warnings.append(error)

    updated_crate = replace(
        import_crate_result,
        data_persistence=_infer_data_persistence(import_crate_result),
    )

    return InspectCrateResult(
        status=InspectCrateStatus.SUCCEEDED,
        import_crate_result=updated_crate,
        warnings=tuple(warnings),
        notes=("Crate inspection completed",),
        inspect_output=inspect_output,
    )

def get_workflow_entities(import_crate_result: ImportCrateResult) -> str | None:
    if import_crate_result.rocrate is None:
        return None
    
    has_part = import_crate_result.rocrate.root_dataset.get("hasPart", [])
    return has_part

def _infer_data_persistence(import_crate_result: ImportCrateResult) -> DataPersistenceKind:
    if import_crate_result.rocrate is None:
        return DataPersistenceKind.UNKNOWN

    has_part = get_workflow_entities(import_crate_result)

    candidate_ids: list[str] = []
    for item in has_part:
        entity_id = item.id
        candidate_ids.append(entity_id)

    has_dataset_refs = any(item.startswith("dataset/") for item in candidate_ids)

    if has_dataset_refs:
        data_persistence = DataPersistenceKind.TRUE
    else:
        data_persistence = DataPersistenceKind.FALSE

    return data_persistence

def _verify_rocrate(inspect_crate_result: InspectCrateResult, file_system) -> InspectCrateResult:

    import_crate_result = inspect_crate_result.import_crate_result
    has_part = get_workflow_entities(import_crate_result)

    if has_part:
        artifacts = []
        for item in has_part:
            entity_kind = check_type_of_entity(item)
            entity_path = inspect_crate_result.import_crate_result.crate_location / item.id
            entity = WorkflowEntity(type=entity_kind,name=item.id,path=entity_path,accessible=file_system.exists(entity_path),exists=file_system.exists(entity_path))
            artifacts.append(entity)

        entity_summary = WorkflowEntitySummary(artifacts=artifacts)

        metadata = inspect_crate_result.import_crate_result.metadata
        if metadata:
            updated_metadata = replace(metadata, workflow_artifact_summary=entity_summary)
            updated_import_crate_result = replace(
                inspect_crate_result.import_crate_result,
                metadata=updated_metadata,
            )
            inspect_crate_result = replace(
                inspect_crate_result,
                import_crate_result=updated_import_crate_result,
            )

    return inspect_crate_result

def check_type_of_entity(item: dict) -> EntityKind:
    
    entity_type = item.type
    entity_name = item.id
    if "SoftwareSourceCode" in entity_type:
        return EntityKind.SOFTWARE_SOURCE_CODE
    elif "ImageObject" in entity_type:
        return EntityKind.IMAGE_OBJECT
    elif "File" in entity_type and entity_name.startswith("dataset/"):
        return EntityKind.INPUT_OR_OUTPUT
    elif entity_name.endswith("README"):
        return EntityKind.README
    elif entity_name.startswith("compss_submission_command_line"):
        return EntityKind.COMPSS_SUBMISSION_COMMAND_LINE_FILE
    else:
        return EntityKind.UNKNOWN
