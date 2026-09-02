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
from pathlib import Path

from domain.models.crate import (
    WorkflowEntity,
    WorkflowMetadata,
    WorkflowParticipant,
)
from application.use_cases.import_crate import DataPersistenceKind


def build_workflow_metadata(
    name: str,
    description: str = "",
    version: str | None = None,
    authors: tuple[WorkflowParticipant, ...] = (),
    submitter: WorkflowParticipant | None = None,
    source_metadata_path: Path | None = None,
) -> WorkflowMetadata:
    return WorkflowMetadata(
        name=name,
        description=description,
        version=version,
        authors=authors,
        submitter=submitter,
        source_metadata_path=source_metadata_path,
    )