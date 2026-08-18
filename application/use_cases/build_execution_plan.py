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
import token
from typing import Protocol, runtime_checkable
import os
from rocrate.rocrate import ROCrate

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
    "--heterogeneous",
    "--sc_cfg",
    "--exec_time",
    "--job_name",
    "--queue",
    "--reservation",
    "--job_execution_dir",
    "--pre_env_script",
    "--extra_submit_flag",
    "--storage_container_image",
    "--storage_cpu_affinity",
    "--constraints",
    "--project_name",
    "--qos",
    "--forward_cpus_per_node",
    "--job_dependency",
    "--forward_time_limit",
    "--storage_home",
    "--storage_props",
    "--agents",
    "--num_nodes",
    "--num_switches",
    "--type_cfg",
    "--master",
    "--workers",
    "--cpus_per_node",
    "--gpus_per_node",
    "--fpgas_per_node",
    "--io_executors",
    "--fpga_reprogram",
    "--max_tasks_per_node",
    "--node_memory",
    "--node_storage_bandwidth",
    "--network",
    "--prolog",
    "--epilog",
    "--master_working_dir",
    "--worker_working_dir",
    "--worker_in_master_cpus",
    "--worker_in_master_memory",
    "--worker_port_range",
    "--jvm_worker_in_master_opts",
    "--container_image",
    "--container_compss_path",
    "--container_opts",
    "--elasticity",
    "--automatic_scaling",
    "--jupyter_notebook",
    "--ipython",
    "--ear",
    "--pythonpath",
    "--workers",
}

_PATH_VALUE_FLAGS = {
    "--pythonpath",
}

class FlagValueKind(str, Enum):
    NONE = "none"
    BOOL = "bool"
    INT = "int"
    STRING = "string"
    PATH = "path"
    DIRECTORY = "directory"

@dataclass(frozen=True, slots=True)
class FlagDefinition:
    name: str
    description: str
    backend_scope: tuple[ExecutionBackend, ...]
    value_kind: FlagValueKind = FlagValueKind.NONE
    aliases: tuple[str, ...] = ()
    repeatable: bool = False
    prefer_equals: bool = False

FLAG_DEFINITIONS: tuple[FlagDefinition, ...] = (
    FlagDefinition("--debug", "Enable debug mode", (ExecutionBackend.LOCAL, ExecutionBackend.SLURM), aliases=("-d",)),
    FlagDefinition("--log_level", "Set log level", (ExecutionBackend.LOCAL, ExecutionBackend.SLURM), FlagValueKind.STRING, prefer_equals=True),
    FlagDefinition("--lang", "Language for the COMPSs runtime", (ExecutionBackend.LOCAL, ExecutionBackend.SLURM), FlagValueKind.STRING, prefer_equals=True),
    FlagDefinition("--num_nodes", "Number of nodes", (ExecutionBackend.SLURM,), FlagValueKind.INT, prefer_equals=True),
    FlagDefinition("--queue", "SLURM queue", (ExecutionBackend.SLURM,), FlagValueKind.STRING, prefer_equals=True),
    FlagDefinition("--pythonpath", "Python path", (ExecutionBackend.LOCAL,), FlagValueKind.PATH, prefer_equals=True),
    FlagDefinition("--provenance", "Enable provenance", (ExecutionBackend.LOCAL, ExecutionBackend.SLURM), FlagValueKind.NONE, aliases=("-p",)),
    FlagDefinition("--zip_provenance", "Generate ZIP provenance output", (ExecutionBackend.LOCAL, ExecutionBackend.SLURM), FlagValueKind.NONE, aliases=("-z",)),
)

class SubmissionCommandEditKind(str, Enum):
    ADD = "add"
    REMOVE = "remove"
    SET_VALUE = "set_value"

@dataclass(frozen=True, slots=True)
class SubmissionCommandEdit:
    kind: SubmissionCommandEditKind
    name: str
    value: str | None = None

FLAG_BY_NAME = {flag.name: flag for flag in FLAG_DEFINITIONS}
FLAG_BY_ALIAS = {alias: flag.name for flag in FLAG_DEFINITIONS for alias in flag.aliases}

class BuildExecutionPlanStatus(str, Enum):
    PENDING = "pending"
    READY = "ready"
    FAILED = "failed"

@dataclass(frozen=True, slots=True)
class ParsedFlag:
    definition_name: str | None
    token: str
    value: str | None = None
    raw_tokens: tuple[str, ...] = ()

@dataclass(frozen=True, slots=True)
class ParsedSubmissionCommand:
    executable: str
    flags: tuple[ParsedFlag, ...]
    positionals: tuple[str, ...]

@dataclass(frozen=True, slots=True)
class BuildExecutionPlanRequest:
    crate: CrateSummary
    workspace_directory: Path
    backend: ExecutionBackend = ExecutionBackend.AUTO
    provenance_enabled: bool = False
    submission_command: str | None = None
    runtime_executable: str | None = None
    submission_edits: tuple[SubmissionCommandEdit, ...] = ()


    def __post_init__(self) -> None:
        if self.crate is None:
            raise ValidationError("BuildExecutionPlanRequest.crate cannot be None")
        if not str(self.workspace_directory).strip():
            raise ValidationError("BuildExecutionPlanRequest.workspace_directory cannot be empty")


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
        results_dir_name: str = "Result",
    ) -> None:
        self._backend_detector = backend_detector
        self._log_dir_name = log_dir_name
        self._results_dir_name = results_dir_name

    def execute(self, request: BuildExecutionPlanRequest) -> BuildExecutionPlanResult:
        backend = self._select_backend(request)
        context = self._build_context(request, backend)
        command = self.build_command(
            request=request,
            backend=backend,
            execution_directory=context.execution_directory,
        )
        plan = ExecutionPlan(
            backend=backend,
            command=command,
            context=context,
            provenance_enabled=request.provenance_enabled,
        )
        submission = ExecutionSubmission(
            command=command,
            backend=backend,
            workspace_directory=context.workspace_directory,
            log_directory=context.log_directory,
            results_directory=context.results_directory,
        )

        warnings: list[str] = []
        notes: list[str] = []

        if request.provenance_enabled:
            notes.append("Provenance is enabled")

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
            workspace_directory=request.workspace_directory,
            log_directory=request.workspace_directory / self._log_dir_name,
            results_directory=request.workspace_directory / self._results_dir_name,
        )

    def build_command( self, request: BuildExecutionPlanRequest, backend: ExecutionBackend, execution_directory: Path | None = None ) -> RuntimeCommand:
        raw_command = request.submission_command or self._discover_command(request.crate)
        if not raw_command:
            raise BuildExecutionPlanFailure("Could not determine the submission command")

        schema = {flag.name: flag for flag in FLAG_DEFINITIONS}
        crate_root = request.crate.location.copied_downloaded_crate_path

        parsed = self.parse_submission_command(raw_command, schema)
        parsed = self.normalize_executable(parsed, backend, request.runtime_executable)
        parsed = self.strip_unsupported_for_backend(parsed, backend)
        parsed = self.remap_paths(parsed, crate_root)
        parsed = self.strip_provenance(parsed)

        edits = list(request.submission_edits)
        if request.provenance_enabled:
            has_provenance_add = any(
                edit.kind == SubmissionCommandEditKind.ADD
                and edit.name.split(" - ", 1)[0].split("=", 1)[0].strip() in {"--provenance", "-p"}
                for edit in edits
            )
            if not has_provenance_add:
                edits.append(
                    SubmissionCommandEdit(
                        kind=SubmissionCommandEditKind.ADD,
                        name="--provenance",
                    )
                )
        parsed = self.apply_edits(parsed, tuple(edits))

        return self.serialize_submission_command(parsed, working_directory=execution_directory)


    def serialize_submission_command(
        self,
        parsed: ParsedSubmissionCommand,
        working_directory: Path | None = None,
    ) -> RuntimeCommand:
        arguments: list[str] = []
    
        for flag in parsed.flags:
            if flag.value is None:
                arguments.append(flag.token)
                continue
    
            definition = None
            if flag.definition_name:
                definition = self.resolve_flag_definition(flag.definition_name)
    
            if definition is not None and definition.prefer_equals:
                arguments.append(f"{flag.token}={flag.value}")
            elif "=" in flag.token:
                arguments.append(f"{flag.token}={flag.value}")
            else:
                arguments.extend([flag.token, flag.value])
    
        arguments.extend(parsed.positionals)
    
        return RuntimeCommand(
            executable=parsed.executable,
            arguments=tuple(arguments),
            working_directory=working_directory,
        )

    def parse_submission_command(self, raw_command: str, schema: dict[str, FlagDefinition]) -> ParsedSubmissionCommand:
        parts = [part for part in raw_command.strip().split() if part]
        if not parts:
            raise BuildExecutionPlanFailure("The submission command is empty")

        executable = parts[0]
        flags: list[ParsedFlag] = []
        positionals: list[str] = []
        
        index = 1
        while index < len(parts):
            token = parts[index]
        
            if not token.startswith("-"):
                positionals.append(token)
                index += 1
                continue
        
            token_name = token.split("=", 1)[0]
            definition = self.validate_flag_token(token_name, backend=None)
        
            # Unknown flags are preserved as-is instead of failing.
            if definition is None:
                if "=" in token:
                    raw_name, raw_value = token.split("=", 1)
                    flags.append(
                        ParsedFlag(
                            definition_name=None,
                            token=raw_name,
                            value=raw_value,
                            raw_tokens=(token,),
                        )
                    )
                else:
                    flags.append(
                        ParsedFlag(
                            definition_name=None,
                            token=token,
                            value=None,
                            raw_tokens=(token,),
                        )
                    )
                index += 1
                continue
        
            canonical_name = definition.name
            value = None
            raw_tokens = [token]
        
            if "=" in token:
                _, value = token.split("=", 1)
            else:
                if definition.value_kind != FlagValueKind.NONE:
                    if index + 1 >= len(parts) or parts[index + 1].startswith("-"):
                        raise BuildExecutionPlanFailure(f"Flag {definition.name} requires a value")
                    value = parts[index + 1]
                    raw_tokens.append(parts[index + 1])
                    index += 1
        
            if definition.value_kind == FlagValueKind.NONE and value is not None:
                raise BuildExecutionPlanFailure(f"Flag {definition.name} does not accept a value")
        
            flags.append(
                ParsedFlag(
                    definition_name=definition.name,
                    token=canonical_name,
                    value=value,
                    raw_tokens=tuple(raw_tokens),
                )
            )
            index += 1
        
        return ParsedSubmissionCommand(
            executable=executable,
            flags=tuple(flags),
            positionals=tuple(positionals),
        )

    def canonical_name(self, token: str | None) -> str | None:
        if token is None:
            return None
        base = token.split("=", 1)[0].strip()
        return FLAG_BY_ALIAS.get(base, base)

    def flag_matches(self, flag: ParsedFlag, target: str) -> bool:
        token_base = flag.token.split("=", 1)[0]
        token_canonical = FLAG_BY_ALIAS.get(token_base, token_base)
        definition_canonical = FLAG_BY_ALIAS.get(flag.definition_name, flag.definition_name) if flag.definition_name else None
        return token_canonical == target or definition_canonical == target

    def normalize_name(self, name: str) -> str:
        raw = name.split(" - ", 1)[0].strip()
        base = raw.split("=", 1)[0]
        return base

    def apply_edits(
        self,
        parsed: ParsedSubmissionCommand,
        edits: tuple[SubmissionCommandEdit, ...],
    ) -> ParsedSubmissionCommand:
        flags = list(parsed.flags)

        for edit in edits:
            target = self.canonical_name(edit.name)
            definition = self.resolve_flag_definition(edit.name)

            if definition is None:
                definition = next(
                    (flag for flag in FLAG_DEFINITIONS if flag.name == target or target in flag.aliases),
                    None,
                )

            first_idx = next(
                (i for i, flag in enumerate(flags) if self.flag_matches(flag, target)),
                None,
            )

            if edit.kind == SubmissionCommandEditKind.ADD:
                if definition is not None and definition.repeatable:
                    flags.append(self.build_flag(edit.name, edit.value))
                    continue

                if first_idx is not None:
                    existing_token = flags[first_idx].token.split("=", 1)[0]
                    flags[first_idx] = self.build_flag(existing_token, edit.value)
                else:
                    flags.append(self.build_flag(edit.name, edit.value))

            elif edit.kind == SubmissionCommandEditKind.REMOVE:
                flags = [flag for flag in flags if not self.flag_matches(flag, target)]

            elif edit.kind == SubmissionCommandEditKind.SET_VALUE:
                if first_idx is not None:
                    existing_token = flags[first_idx].token.split("=", 1)[0]
                    flags[first_idx] = self.build_flag(existing_token, edit.value)
                else:
                    flags.append(self.build_flag(edit.name, edit.value))

        return ParsedSubmissionCommand(
            executable=parsed.executable,
            flags=tuple(flags),
            positionals=parsed.positionals,
        )

    def strip_provenance(self, parsed: ParsedSubmissionCommand) -> ParsedSubmissionCommand:
        filtered = [
            flag
            for flag in parsed.flags
            if self.canonical_name(flag.token) not in {"--provenance", "-p"}
            and self.canonical_name(flag.definition_name) not in {"--provenance", "-p"}
        ]
        return ParsedSubmissionCommand(
            executable=parsed.executable,
            flags=tuple(filtered),
            positionals=parsed.positionals,
        )
    
    def strip_unsupported_for_backend(
        self,
        parsed: ParsedSubmissionCommand,
        backend: ExecutionBackend,
    ) -> ParsedSubmissionCommand:
        if backend != ExecutionBackend.LOCAL:
            return parsed
    
        filtered_flags = [
            flag
            for flag in parsed.flags
            if self.canonical_name(flag.token) not in _LOCAL_UNSUPPORTED_FLAGS
            and self.canonical_name(flag.definition_name) not in _LOCAL_UNSUPPORTED_FLAGS
        ]
        return ParsedSubmissionCommand(
            executable=parsed.executable,
            flags=tuple(filtered_flags),
            positionals=parsed.positionals,
        )

    def normalize_executable(self,
        parsed: ParsedSubmissionCommand,
        backend: ExecutionBackend,
        runtime_executable: str | None,
    ) -> ParsedSubmissionCommand:
        executable = runtime_executable or ("enqueue_compss" if backend == ExecutionBackend.SLURM else "runcompss")
        return ParsedSubmissionCommand(
            executable=executable,
            flags=parsed.flags,
            positionals=parsed.positionals,
        )

    def remap_paths(self, parsed: ParsedSubmissionCommand, crate_root: Path) -> ParsedSubmissionCommand:
        remapped_flags: list[ParsedFlag] = []
        for flag in parsed.flags:
            if flag.value is None:
                remapped_flags.append(flag)
            else:
                remapped_flags.append(
                    ParsedFlag(
                        definition_name=flag.definition_name,
                        token=flag.token,
                        value=self._remap_single_argument(flag.value, crate_root),
                        raw_tokens=flag.raw_tokens,
                    )
                )

        remapped_positionals = tuple(
            self._remap_single_argument(argument, crate_root)
            for argument in parsed.positionals
        )
        return ParsedSubmissionCommand(
            executable=parsed.executable,
            flags=tuple(remapped_flags),
            positionals=remapped_positionals,
        )


    def _remap_single_argument(self, arg: str, crate_root: Path) -> str:
        had_trailing_slash = arg.endswith("/") and arg != "/"

        expanded = os.path.expanduser(arg)
        path = Path(expanded)

        if path.is_absolute():
            if path.exists():
                return arg

            candidates = self._candidate_local_paths(path, crate_root)
            for candidate in candidates:
                if candidate.exists():
                    return self._format_mapped_path(candidate, had_trailing_slash)
        else:
            candidates = self._candidate_relative_paths(path, crate_root)
            for candidate in candidates:
                if candidate.exists():
                    return self._format_mapped_path(candidate, had_trailing_slash)

        basename_matches = list(crate_root.rglob(path.name))
        if len(basename_matches) == 1 and basename_matches[0].exists():
            return self._format_mapped_path(basename_matches[0], had_trailing_slash)

        return arg


    def _candidate_relative_paths(self, original: Path, crate_root: Path) -> list[Path]:
        candidates: list[Path] = []
        if original.parts:
            candidates.append(crate_root.joinpath(*original.parts))

            head = original.parts[0]
            tail = original.parts[1:]
            if head in {"src", "application_sources", "datasets", "dataset", "data"} and tail:
                candidates.append(crate_root / "application_sources" / Path(*tail))
                candidates.append(crate_root / "src" / Path(*tail))

        candidates.append(crate_root / "application_sources" / original.name)
        candidates.append(crate_root / original.name)

        unique: list[Path] = []
        seen: set[str] = set()
        for candidate in candidates:
            key = str(candidate)
            if key not in seen:
                unique.append(candidate)
                seen.add(key)
        return unique


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

        candidates.append(crate_root / "application_sources" / "src" / original.name)

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
        crate_root = crate.location.copied_downloaded_crate_path
    
        for path in [crate_root / "compss_submission_command_line.txt", *sorted(crate_root.rglob("compss_submission_command_line.txt"))]:
            if path.is_file():
                first_line = path.read_text(encoding="utf-8").splitlines()
                if first_line:
                    command = self._normalize_submission_command(first_line[0])
                    if command:
                        return command
    
        rocrate = self._load_rocrate(crate_root)
        if rocrate:
            command = self._extract_command_from_rocrate(rocrate)
            if command:
                return command
    
        return None
    
    
    def _load_rocrate(self, crate_root: Path) -> ROCrate | None:
        try:
            return ROCrate(crate_root)
        except Exception:
            return None
    
    
    def _extract_command_from_rocrate(self, crate: ROCrate) -> str | None:
        graph = list(crate.get_entities())
    
        # 1. Prefer the workflow-level entity
        main_entity = crate.root_dataset.get("mainEntity")
        for entity in graph:
            if entity == main_entity:
                command = self._normalize_submission_command(entity.get("description"))
                if command:
                    return command
    
        # 2. Then prefer the first matching CreateAction
        for entity in graph:
            if self._is_create_action(entity):
                command = self._normalize_submission_command(entity.get("description"))
                if command:
                    return command
    
        # 3. Then any other usable description
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

    def build_flag(self,token_name: str, value: str | None) -> ParsedFlag:
        base = self.normalize_name(token_name)
        canonical = FLAG_BY_ALIAS.get(base, base)
        definition_name = canonical if canonical in FLAG_BY_NAME else None
        raw_tokens = (base,) if value is None else (base, value)
        return ParsedFlag(
            definition_name=definition_name,
            token=base,
            value=value,
            raw_tokens=raw_tokens,
        )

    def resolve_flag_definition(self, name: str | None) -> FlagDefinition | None:
        if not name:
            return None
        canonical = self.canonical_name(name)
        return FLAG_BY_NAME.get(canonical)

    def validate_flag_token(self, token: str, backend: ExecutionBackend | None = None) -> FlagDefinition | None:
        canonical = self.canonical_name(token)
        if canonical is None:
            return None
    
        definition = self.resolve_flag_definition(canonical)
        if definition is None:
            return None
    
        if backend is not None and backend not in definition.backend_scope:
            return None
    
        return definition