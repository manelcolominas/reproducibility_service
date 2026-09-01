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

from application.ports.metadata_parser import (
    MetadataDocument,
    MetadataFormat,
    MetadataNormalizationResult,
    MetadataParseRequest,
    MetadataSource,
    MetadataSourceKind,
)
from infrastructure.adapters import (
    CrateMetadataParser,
    CrateMetadataNormalizer,
    LocalPyCompssMetadataInspector,
)
from domain.errors import ValidationError
# from domain.models.crate import CrateSummary
from domain.models.verification import VerificationSummary


class InspectCrateStatus(str, Enum):
    PENDING = "pending"
    PARSED = "parsed"
    NORMALIZED = "normalized"
    INSPECTED = "inspected"
    FAILED = "failed"


@dataclass(frozen=True, slots=True)
class InspectCrateRequest:
    crate_root: Path
    metadata_path: Path | None = None

    def __post_init__(self) -> None:
        if not str(self.crate_root).strip():
            raise ValidationError("InspectCrateRequest.crate_root cannot be empty")

@dataclass(frozen=True, slots=True)
class InspectCrateResult:
    status: InspectCrateStatus
    request: InspectCrateRequest
    document: MetadataDocument
    normalization: MetadataNormalizationResult
    #crate: CrateSummary | None = None
    verification: VerificationSummary | None = None
    warnings: tuple[str, ...] = ()
    notes: tuple[str, ...] = ()
    inspect_output: str | None = None
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    @property
    def inspected(self) -> bool:
        return self.status == InspectCrateStatus.INSPECTED

    @property
    def has_warnings(self) -> bool:
        return len(self.warnings) > 0


def _inspect_rocrate_simple(crate_root: Path):
    parser = CrateMetadataParser()
    normalizer = CrateMetadataNormalizer()
    inspector = LocalPyCompssMetadataInspector()

    metadata_source = MetadataSource(
        type=MetadataSourceKind.DIRECTORY,
        location=str(crate_root),
        format_hint=MetadataFormat.UNKNOWN,
    )
    parse_request = MetadataParseRequest(
        source=metadata_source,
        expected_format=MetadataFormat.UNKNOWN,
        allow_partial_metadata=True,
        strict=False,
    )

    document = parser.parse(parse_request)
    normalization = normalizer.normalize(document)

    crate = normalization.crate
    if crate is None and normalization.metadata is not None:
        crate = normalization.metadata

    inspect_output = None
    warnings = list(normalization.warnings)
    try:
        inspection = inspector.inspect(document)
        inspect_output = inspection.stdout
        if inspection.warning:
            warnings.append(inspection.warning)
    except Exception as exc:
        warnings.append(f"pycompss inspect failed: {exc}")

    status = InspectCrateStatus.INSPECTED if normalization.is_usable else InspectCrateStatus.FAILED

    return InspectCrateResult(
        status=status,
        request=InspectCrateRequest(crate_root=crate_root),
        document=document,
        normalization=normalization,
        crate=crate,
        warnings=tuple(warnings),
        notes=tuple(normalization.issues),
        inspect_output=inspect_output,
    )
