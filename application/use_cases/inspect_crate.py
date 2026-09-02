from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum

from application.use_cases.import_crate import ImportCrateResult

from infrastructure.pycompss_inspect import LocalPyCompssMetadataInspector

class InspectCrateStatus(str, Enum):
    SUCCEEDED = "succeeded"
    FAILED = "failed"


@dataclass(frozen=True, slots=True)
class InspectCrateResult:
    status: InspectCrateStatus
    crate: ImportCrateResult | None = None
    warnings: tuple[str, ...] = ()
    notes: tuple[str, ...] = ()
    inspect_output: str | None = None
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


def _inspect_rocrate(import_crate_result: ImportCrateResult, inspector: LocalPyCompssMetadataInspector ) -> InspectCrateResult:
    warnings: list[str] = []
    inspect_output: str | None = None

    if inspector is not None:
        ok, output, error = inspector.inspect(import_crate_result.crate_location)
        inspect_output = output
        if not ok and error:
            warnings.append(error)

    return InspectCrateResult(
        status=InspectCrateStatus.SUCCEEDED,
        crate=import_crate_result,
        warnings=tuple(warnings),
        notes=("Crate inspection completed",),
        inspect_output=inspect_output,
    )