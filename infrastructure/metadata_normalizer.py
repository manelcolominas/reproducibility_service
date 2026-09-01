
from application.ports.metadata_parser import WorkflowMetadata
from application.ports.metadata_parser import WorkflowArtifact
from pathlib import Path
import os


class CrateMetadataNormalizer:

    def normalize(self, ) -> :
        if document.format == .COMPSS_YAML:
            return self._normalize_compss_yaml(document)
        if document.format == .RO_CRATE_JSON:
            return self._normalize_ro_crate_json(document)
        return ( document=document, warnings=(f"Unsupported metadata format: {document.format}"))

    def _normalize_compss_yaml(self, ) -> :
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
            for item in sources_rawº
            if str(item).strip()
        )
        index = sources=sources)
    
        crate_root = document.path.parent if document.path else Path(document.source.location)
    
        return MetadataNormalizationResult(
            document=document,
            metadata=metadata,
            index=index,
            #crate=crate,
            warnings=tuple(warnings),
        )

    def _normalize_ro_crate_json(self, document: MetadataDocument) -> :
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
            license=root_entity.get("license") or "",
            authors=authors,
            compss_version=compss_version,
            execution_site=execution_site,
            data_persistence=self._infer_data_persistence(root_entity=root_entity, entities_by_id=entities_by_id),
            source_metadata_path=document.path,
        )

        index = sources=sources)

        return (
            document=document,
            metadata=metadata,
            index=index,
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

    def _extract_organization_name(self, person: dict, entities_by_id: dict[str, dict]) -> str | None:
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