from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Protocol, runtime_checkable
import json
import os

from application.ports.executor import (
    ExecutionBackendDetector,
    ExecutionPlanner as ExecutorPlanner,
    ExecutionRequest,
    ExecutionSubmission,
)
from domain.errors import CommandBuildError, ValidationError
from domain.models.crate import CrateSummary, WorkflowCommand
from domain.models.execution import (
    ExecutionBackend,
    ExecutionContext,
    ExecutionPlan,
    RuntimeCommand,
)

_COMMAND_PREFIXES = ("runcompss", "enqueue_compss")

_LOCAL_UNSUPPORTED_FLAGS = {
    "--qos",
    "--job_name",
    "--num_nodes",
    "--exec_time",
    "--project_name",
    "--worker_working_dir",
    "--pythonpath", # pythonpath is supported in local execution
}

_PATH_VALUE_FLAGS = {
    "--pythonpath",
}

class BuildExecutionPlanStatus(str, Enum):
    PENDING = "pending"
    READY = "ready"
    FAILED = "failed"


@dataclass(frozen=True, slots=True)
class BuildExecutionPlanRequest:
    crate: CrateSummary
    run_directory: Path
    backend: ExecutionBackend = ExecutionBackend.AUTO
    provenance_enabled: bool = False
    extra_flags: tuple[str, ...] = ()
    changed_values: tuple[tuple[int, str], ...] = ()
    submission_command: str | None = None
    runtime_executable: str | None = None

    def __post_init__(self) -> None:
        if self.crate is None:
            raise ValidationError("BuildExecutionPlanRequest.crate cannot be None")
        if not str(self.run_directory).strip():
            raise ValidationError("BuildExecutionPlanRequest.run_directory cannot be empty")


@dataclass(frozen=True, slots=True)
class BuildExecutionPlanResult:
    status: BuildExecutionPlanStatus
    request: BuildExecutionPlanRequest
    backend: ExecutionBackend
    command: RuntimeCommand
    plan: ExecutionPlan
    context: ExecutionContext
    submission: ExecutionSubmission
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    warnings: tuple[str, ...] = ()
    notes: tuple[str, ...] = ()

    @property
    def ready(self) -> bool:
        return self.status == BuildExecutionPlanStatus.READY


@runtime_checkable
class BuildExecutionPlanUseCase(Protocol):
    def execute(self, request: BuildExecutionPlanRequest) -> BuildExecutionPlanResult:
        ...


class BuildExecutionPlanPortError(CommandBuildError):
    pass


class BuildExecutionPlanFailure(BuildExecutionPlanPortError):
    pass


class DefaultBuildExecutionPlanService:
    def __init__(
        self,
        backend_detector: ExecutionBackendDetector | None = None,
        log_dir_name: str = "log",
        results_dir_name: str = "Results",
    ) -> None:
        self._backend_detector = backend_detector
        self._log_dir_name = log_dir_name
        self._results_dir_name = results_dir_name

    def execute(self, request: BuildExecutionPlanRequest) -> BuildExecutionPlanResult:
        backend = self._select_backend(request)
        command = self._build_command(request, backend)
        context = self._build_context(request, backend)
        plan = ExecutionPlan(
            backend=backend,
            command=command,
            context=context,
            provenance_enabled=request.provenance_enabled,
            extra_flags=request.extra_flags,
            changed_values=request.changed_values,
        )
        submission = ExecutionSubmission(
            command=command,
            backend=backend,
            run_directory=context.run_directory,
            log_directory=context.log_directory,
            results_directory=context.results_directory,
        )

        warnings: list[str] = []
        notes: list[str] = []

        if request.provenance_enabled:
            notes.append("Provenance is enabled")
        if request.extra_flags:
            notes.append("Extra runtime flags were added")

        return BuildExecutionPlanResult(
            status=BuildExecutionPlanStatus.READY,
            request=request,
            backend=backend,
            command=command,
            plan=plan,
            context=context,
            submission=submission,
            warnings=tuple(warnings),
            notes=tuple(notes),
        )

    def _select_backend(self, request: BuildExecutionPlanRequest) -> ExecutionBackend:
        if request.backend != ExecutionBackend.AUTO:
            return request.backend
        if self._backend_detector is None:
            return ExecutionBackend.LOCAL
        return self._backend_detector.detect()

    def _build_context(
        self,
        request: BuildExecutionPlanRequest,
        backend: ExecutionBackend,
    ) -> ExecutionContext:
        return ExecutionContext(
            backend=backend,
            run_directory=request.run_directory,
            log_directory=request.run_directory / self._log_dir_name,
            results_directory=request.run_directory / self._results_dir_name,
        )

    def _build_command(
        self,
        request: BuildExecutionPlanRequest,
        backend: ExecutionBackend,
        ) -> RuntimeCommand:
        raw_command = request.submission_command or self._discover_command(request.crate)
        if not raw_command:
            raise BuildExecutionPlanFailure("Could not determine the submission command")
    
        parts = [part for part in raw_command.strip().split() if part]
        executable = request.runtime_executable or self._default_executable(backend)
    
        if not parts:
            raise BuildExecutionPlanFailure("The submission command is empty")
    
        parts[0] = executable
    
        arguments = list(parts[1:])
    
        # Local backend should not receive SLURM-only scheduler flags.
        if backend == ExecutionBackend.LOCAL:
            arguments = self._strip_local_unsupported_flags(arguments)
    
        # Remap absolute paths from original environment into local imported crate.
        arguments = self._remap_arguments_to_local_crate(
            arguments=arguments,
            crate_root=request.crate.location.working_path,
        )

        arguments = [argument for argument in arguments if argument != "--provenance" and not argument.startswith("--provenance=")]

        if request.provenance_enabled:
            arguments.insert(0, "--provenance")
        if request.extra_flags:
            arguments = list(request.extra_flags) + arguments
        if request.changed_values:
            for index, value in request.changed_values:
                arguments.extend(["--change", f"{index}={value}"])
    
        return RuntimeCommand(
            executable=parts[0],
            arguments=tuple(arguments),
            working_directory=request.run_directory,
        )

    def _strip_local_unsupported_flags(self, arguments: list[str]) -> list[str]:
        """Drop scheduler-only flags when running locally."""
        cleaned: list[str] = []
        i = 0
        while i < len(arguments):
            token = arguments[i]
    
            if token in _LOCAL_UNSUPPORTED_FLAGS:
                # Skip flag and its value (if present and not another flag)
                i += 1
                if i < len(arguments) and not arguments[i].startswith("-"):
                    i += 1
                continue
    
            # Also support --flag=value form.
            if any(token.startswith(flag + "=") for flag in _LOCAL_UNSUPPORTED_FLAGS):
                i += 1
                continue
    
            cleaned.append(token)
            i += 1
    
        return cleaned
    
    
    def _remap_arguments_to_local_crate(self, arguments: list[str], crate_root: Path) -> list[str]:
        """Translate absolute paths from original execution host to local crate paths."""
        remapped: list[str] = []
        for arg in arguments:
            remapped.append(self._remap_single_argument(arg, crate_root))
        return remapped
    
    
    def _remap_single_argument(self, arg: str, crate_root: Path) -> str:
        # Preserve possible trailing slash semantics from original command.
        had_trailing_slash = arg.endswith("/") and arg != "/"
    
        # Ignore non-path tokens.
        expanded = os.path.expanduser(arg)
        path = Path(expanded)
    
        # Only remap absolute paths.
        if not path.is_absolute():
            return arg
    
        # If it already exists locally, keep as-is.
        if path.exists():
            return arg
    
        # Try known anchors first (common in COMPSs crates).
        candidates = self._candidate_local_paths(path, crate_root)
        for candidate in candidates:
            if candidate.exists():
                return self._format_mapped_path(candidate, had_trailing_slash)
    
        # Fallback: unique basename match under crate root.
        basename_matches = list(crate_root.rglob(path.name))
        if len(basename_matches) == 1 and basename_matches[0].exists():
            return self._format_mapped_path(basename_matches[0], had_trailing_slash)
    
        # If ambiguous or not found, keep original and let runtime surface error.
        return arg
    
    def _candidate_local_paths(self, original: Path, crate_root: Path) -> list[Path]:
        parts = list(original.parts)
    
        anchors = (
            "application_sources",
            "dataset",
            "datasets",
            "data",
            "src",
        )
    
        candidates: list[Path] = []
        for anchor in anchors:
            if anchor in parts:
                idx = parts.index(anchor)
                suffix = parts[idx:]
                candidates.append(crate_root.joinpath(*suffix))
    
        # If path ends in ".../wordcount.py", try under application_sources/src as a smart fallback.
        candidates.append(crate_root / "application_sources" / "src" / original.name)
    
        # Deduplicate preserving order.
        unique: list[Path] = []
        seen: set[str] = set()
        for candidate in candidates:
            key = str(candidate)
            if key not in seen:
                unique.append(candidate)
                seen.add(key)
        return unique
    
    def _format_mapped_path(self, candidate: Path, had_trailing_slash: bool) -> str:
        text = str(candidate)
        if had_trailing_slash and candidate.is_dir() and not text.endswith("/"):
            return text + "/"
        return text

    def _discover_command(self, crate: CrateSummary) -> str | None:
        crate_root = crate.location.working_path

        # 1) txt file fallback, recursive to support wrapped zip roots
        txt_candidates = [crate_root / "compss_submission_command_line.txt"]
        txt_candidates.extend(sorted(crate_root.rglob("compss_submission_command_line.txt")))

        for path in txt_candidates:
            if not path.is_file():
                continue
            first_line = path.read_text(encoding="utf-8").splitlines()
            if not first_line:
                continue
            command = self._normalize_submission_command(first_line[0])
            if command:
                return command

        # 2) ro-crate-metadata.json fallback(s), recursive
        for metadata_path in sorted(crate_root.rglob("ro-crate-metadata.json")):
            command = self._extract_command_from_rocrate_json(metadata_path)
            if command:
                return command

        return None

    def _extract_command_from_rocrate_json(self, metadata_path: Path) -> str | None:
        try:
            raw = json.loads(metadata_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return None

        graph = raw.get("@graph")
        if not isinstance(graph, list):
            return None

        # 1) COMPSs Workflow Run Crate entity
        for entity in graph:
            entity_id = str(entity.get("@id") or entity.get("id") or "")
            if "#COMPSs_Workflow_Run_Crate_" in entity_id:
                command = self._normalize_submission_command(entity.get("description"))
                if command:
                    return command

        # 2) CreateAction
        for entity in graph:
            if self._is_create_action(entity):
                command = self._normalize_submission_command(entity.get("description"))
                if command:
                    return command

        # 3) Any entity description
        for entity in graph:
            command = self._normalize_submission_command(entity.get("description"))
            if command:
                return command

        return None

    def _normalize_submission_command(self, value: object) -> str | None:
        if not isinstance(value, str):
            return None
        text = value.strip()
        for prefix in _COMMAND_PREFIXES:
            if text == prefix or text.startswith(prefix + " "):
                return text
        return None

    def _is_create_action(self, entity: dict) -> bool:
        raw_type = entity.get("@type") or entity.get("type")
        if isinstance(raw_type, str):
            return raw_type == "CreateAction"
        if isinstance(raw_type, list):
            return any(str(t) == "CreateAction" for t in raw_type)
        return False

    def _default_executable(self, backend: ExecutionBackend) -> str:
        return "enqueue_compss" if backend == ExecutionBackend.SLURM else "runcompss"