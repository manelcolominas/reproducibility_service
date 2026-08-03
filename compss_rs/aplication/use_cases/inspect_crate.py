from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Protocol, runtime_checkable

from compss_rs.application.ports.metadata_parser import (
    MetadataDocument,
    MetadataFormat,
    MetadataNormalizationOptions,
    MetadataNormalizationResult,
    MetadataNormalizer,
    MetadataParseRequest,
    MetadataParser,
    MetadataPortError,
    MetadataSchema,
    MetadataSource,
    MetadataSourceKind,
)
from compss_rs.domain.errors import ValidationError
from compss_rs.domain.models.crate import CrateCompatibilityReport, CrateSummary, WorkflowMetadata
from compss_rs.domain.models.verification import VerificationSummary


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
    expected_format: MetadataFormat = MetadataFormat.UNKNOWN
    allow_partial_metadata: bool = True
    allow_legacy_fields: bool = True
    strict: bool = False
    collect_warnings: bool = True

    def __post_init__(self) -> None:
        if not str(self.crate_root).strip():
            raise ValidationError("InspectCrateRequest.crate_root cannot be empty")


@dataclass(frozen=True, slots=True)
class InspectCrateResult:
    status: InspectCrateStatus
    crate_root: Path
    metadata_source: MetadataSource
    parse_request: MetadataParseRequest
    document: MetadataDocument
    normalization: MetadataNormalizationResult
    metadata: WorkflowMetadata | None
    crate: CrateSummary | None
    compatibility: CrateCompatibilityReport | None = None
    verification: VerificationSummary | None = None
    warnings: tuple[str, ...] = ()
    notes: tuple[str, ...] = ()
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    @property
    def inspected(self) -> bool:
        return self.status == InspectCrateStatus.INSPECTED

    @property
    def has_warnings(self) -> bool:
        return len(self.warnings) > 0

    @property
    def has_notes(self) -> bool:
        return len(self.notes) > 0

    @property
    def has_compatibility_report(self) -> bool:
        return self.compatibility is not None


@dataclass(frozen=True, slots=True)
class CrateInspectionPlan:
    request: InspectCrateRequest
    metadata_source: MetadataSource
    parse_request: MetadataParseRequest
    normalization_options: MetadataNormalizationOptions
    expected_schema: MetadataSchema | None = None

    def __post_init__(self) -> None:
        if not str(self.request.crate_root).strip():
            raise ValidationError("CrateInspectionPlan.request.crate_root cannot be empty")


@runtime_checkable
class CrateInspectionUseCase(Protocol):
    def execute(self, request: InspectCrateRequest) -> InspectCrateResult:
        """
        Inspect the crate metadata and return a canonical inspection result.
        """
        ...


@runtime_checkable
class CrateInspectionPlanner(Protocol):
    def build_plan(self, request: InspectCrateRequest) -> CrateInspectionPlan:
        """
        Build the plan required to inspect the crate.
        """
        ...


@runtime_checkable
class CrateCompatibilityEvaluator(Protocol):
    def evaluate(self, result: MetadataNormalizationResult) -> CrateCompatibilityReport:
        """
        Evaluate compatibility between the crate metadata and the current runtime.
        """
        ...


class InspectCratePortError(MetadataPortError):
    pass


class InspectCrateFailure(InspectCratePortError):
    def __init__(self, message: str, details: str | None = None):
        super().__init__(message=message, details=details, recoverable=False)


class DefaultCrateInspectionService:
    def __init__(
        self,
        parser: MetadataParser,
        normalizer: MetadataNormalizer,
        compatibility_evaluator: CrateCompatibilityEvaluator | None = None,
    ) -> None:
        self._parser = parser
        self._normalizer = normalizer
        self._compatibility_evaluator = compatibility_evaluator

    def build_plan(self, request: InspectCrateRequest) -> CrateInspectionPlan:
        metadata_source = MetadataSource(
            kind=MetadataSourceKind.DIRECTORY,
            location=str(request.crate_root),
            format_hint=request.expected_format,
            description="Crate root inspection source",
        )
        parse_request = MetadataParseRequest(
            source=metadata_source,
            expected_format=request.expected_format,
            allow_legacy_fields=request.allow_legacy_fields,
            allow_partial_metadata=request.allow_partial_metadata,
            strict=request.strict,
        )
        normalization_options = MetadataNormalizationOptions(
            collect_warnings=request.collect_warnings,
        )
        return CrateInspectionPlan(
            request=request,
            metadata_source=metadata_source,
            parse_request=parse_request,
            normalization_options=normalization_options,
        )

    def execute(self, request: InspectCrateRequest) -> InspectCrateResult:
        plan = self.build_plan(request)

        try:
            document = self._parser.parse(plan.parse_request)
            normalization = self._normalizer.normalize(document, plan.normalization_options)
        except Exception as exc:
            raise InspectCrateFailure("Failed to inspect crate metadata", details=str(exc)) from exc

        metadata = normalization.metadata
        crate = normalization.crate

        compatibility = None
        warnings = list(normalization.warnings)

        if self._compatibility_evaluator is not None:
            compatibility = self._compatibility_evaluator.evaluate(normalization)
            warnings.extend(compatibility.warnings)

        if crate is None and metadata is not None:
            crate = CrateSummary(
                source=document.source.location,
                location=None,  # type: ignore[arg-type]
                metadata=metadata,
            )

        if crate is None:
            warnings.append("Metadata was parsed but could not be normalized into a crate summary")

        status = (
            InspectCrateStatus.INSPECTED
            if metadata is not None or crate is not None
            else InspectCrateStatus.FAILED
        )

        return InspectCrateResult(
            status=status,
            crate_root=request.crate_root,
            metadata_source=plan.metadata_source,
            parse_request=plan.parse_request,
            document=document,
            normalization=normalization,
            metadata=metadata,
            crate=crate,
            compatibility=compatibility,
            warnings=tuple(warnings),
            notes=tuple(normalization.issues[i].message for i in range(len(normalization.issues))),
        )


def has_compatibility_report(result: InspectCrateResult) -> bool:
    return result.compatibility is not None


def has_metadata(result: InspectCrateResult) -> bool:
    return result.metadata is not None


def has_crate_summary(result: InspectCrateResult) -> bool:
    return result.crate is not None


__all__ = [
    "CrateCompatibilityEvaluator",
    "CrateInspectionPlan",
    "CrateInspectionUseCase",
    "DefaultCrateInspectionService",
    "InspectCrateFailure",
    "InspectCratePortError",
    "InspectCrateRequest",
    "InspectCrateResult",
    "InspectCrateStatus",
    "has_compatibility_report",
    "has_crate_summary",
    "has_metadata",
]