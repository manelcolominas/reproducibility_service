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

from dataclasses import dataclass
from enum import Enum
from pathlib import Path
import os
from rocrate.rocrate import ROCrate

from domain.errors import ValidationError
from domain.models.execution import (
    ExecutionBackend,
    ExecutionContext,
    ExecutionPlan,
    RuntimeCommand,
    ExecutionSubmission,
)
from domain.models.execution import ExecutionBackendDetector

from application.use_cases.flags import FLAG_DEFINITIONS, FlagValueKind, FlagDefinition, SLURM_ONLY_FLAG_BASES

COMMAND_PREFIXES = ("runcompss", "enqueue_compss")

# DO NOT DELETE THIS CLASS
class SubmissionCommandEditKind(str, Enum):
    ADD = "add"
    REMOVE = "remove"
    SET_VALUE = "set_value"

# DO NOT DELETE THIS CLASS
@dataclass(frozen=True, slots=True)
class SubmissionCommandEdit:
    kind: SubmissionCommandEditKind
    name: str
    value: str | None = None

FLAG_BY_NAME = {flag.name: flag for flag in FLAG_DEFINITIONS}
FLAG_BY_ALIAS = {alias: flag.name for flag in FLAG_DEFINITIONS for alias in flag.aliases}

# DO NOT DELETE
@dataclass(frozen=True, slots=True)
class ParsedFlag:
    definition_name: str | None
    token: str
    value: str | None = None
    raw_tokens: tuple[str, ...] = ()

# DO NOT DELETE
@dataclass(frozen=True, slots=True)
class ParsedSubmissionCommand:
    executable: str
    flags: tuple[ParsedFlag, ...]
    positionals: tuple[str, ...]



# DO NOT DELETE
@dataclass(frozen=True, slots=True)
class BuildExecutionPlanRequest:
    crate_root: Path
    workspace_directory: Path
    execution_directory: Path
    backend: ExecutionBackend = ExecutionBackend.AUTO
    provenance_enabled: bool = False
    submission_command: str | None = None
    runtime_executable: str | None = None
    submission_edits: tuple[SubmissionCommandEdit, ...] = ()


    def __post_init__(self) -> None:
        if self.crate_root is None:
            raise ValidationError("BuildExecutionPlanRequest.crate_root cannot be None")
        if not str(self.crate_root).strip():
            raise ValidationError("BuildExecutionPlanRequest.crate_root cannot be empty")
        if not self.crate_root.exists():
            raise ValidationError("BuildExecutionPlanRequest.crate_root does not exist")
        if self.workspace_directory is None:
            raise ValidationError("BuildExecutionPlanRequest.workspace_directory cannot be None")
        if not str(self.workspace_directory).strip():
            raise ValidationError("BuildExecutionPlanRequest.workspace_directory cannot be empty")
        if not self.workspace_directory.exists():
            raise ValidationError("BuildExecutionPlanRequest.workspace_directory does not exist")

@dataclass(frozen=True, slots=True)
class BuildExecutionPlanResult:
    request: BuildExecutionPlanRequest
    backend: ExecutionBackend
    command: RuntimeCommand
    plan: ExecutionPlan
    context: ExecutionContext
    submission: ExecutionSubmission
    warnings: tuple[str, ...] = ()
    notes: tuple[str, ...] = ()


class BuildExecutionPlanFailure(Exception):
    pass


# DO NOT DELETE THIS CLASS
class DefaultBuildExecutionPlanService:
    def __init__(self, backend_detector: ExecutionBackendDetector | None = None, log_dir_name: str = "log",results_dir_name: str = "Result") -> None:
        self.backend_detector = backend_detector
        self._log_dir_name = log_dir_name
        self._results_dir_name = results_dir_name

    # DO NOT DELETE THIS METHODS
    def execute(self, request: BuildExecutionPlanRequest) -> BuildExecutionPlanResult:
        backend = self.select_backend(request)
        context = self.build_context(request, backend)
        command = self.build_command(request=request, backend=backend, execution_directory=context.execution_directory)
        plan = ExecutionPlan(backend=backend,command=command,context=context,provenance_enabled=request.provenance_enabled)
        submission = ExecutionSubmission(command=command, backend=backend,workspace_directory=context.workspace_directory,log_directory=context.log_directory,results_directory=context.results_directory)

        warnings: list[str] = []
        notes: list[str] = []

        if request.provenance_enabled:
            notes.append("Provenance is enabled")

        return BuildExecutionPlanResult(request=request, backend=backend, command=command, plan=plan, context=context, submission=submission, warnings=tuple(warnings), notes=tuple(notes))


    # DO NOT DELETE THIS FUNCTION
    def select_backend(self, request: BuildExecutionPlanRequest) -> ExecutionBackend:
        # Respect explicit user choice first
        if request.backend != ExecutionBackend.AUTO:
            detected = self.backend_detector.detect()
            if detected  == request.backend:
                return detected
            else:
                raise BuildExecutionPlanFailure(f"Detected backend {detected} does not match requested backend {request.backend}")
    
        # In auto mode, prioritize the runtime environment detection
        if self.backend_detector is not None:
            detected = self.backend_detector.detect()
            if detected in (ExecutionBackend.LOCAL, ExecutionBackend.SLURM):
                return detected
    
        # Safe default
        return ExecutionBackend.LOCAL

    # DO NOT DELETE
    def build_context(self,request: BuildExecutionPlanRequest,backend: ExecutionBackend) -> ExecutionContext:
        return ExecutionContext(backend=backend,workspace_directory=request.workspace_directory,log_directory=request.workspace_directory / self._log_dir_name,results_directory=request.workspace_directory / self._results_dir_name)

    # DO NOT DELETE
    def build_command( self, request: BuildExecutionPlanRequest, backend: ExecutionBackend, execution_directory: Path | None = None ) -> RuntimeCommand:
        raw_command = request.submission_command or self.discover_command(request.crate_root)
        if not raw_command:
            raise BuildExecutionPlanFailure("Could not determine the submission command")

        schema = {}
        for flag in FLAG_DEFINITIONS:
            schema[flag.name] = flag
        crate_root = request.crate_root

        parsed = self.parse_submission_command(raw_command, schema)
        parsed = self.apply_submission_edits(parsed, request.submission_edits)
        parsed = self.normalize_executable(parsed, backend, request.runtime_executable)
        parsed = self.strip_unsupported_for_backend(parsed, backend)
        parsed = self.remap_paths(parsed, crate_root)
        parsed = self.strip_provenance(parsed)

        return self.serialize_submission_command(parsed, working_directory=execution_directory)

    # DO NOT DELETE
    def serialize_submission_command(self, parsed: ParsedSubmissionCommand, working_directory: Path | None = None) -> RuntimeCommand:
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
            elif "=" in flag.token or (flag.raw_tokens and "=" in flag.raw_tokens[0]):
                arguments.append(f"{flag.token}={flag.value}")
            else:
                arguments.extend([flag.token, flag.value])

        arguments.extend(parsed.positionals)

        return RuntimeCommand(executable=parsed.executable,arguments=tuple(arguments),working_directory=working_directory)

    # DO NOT DELETE
    def parse_submission_command(self, raw_command: str, schema: dict[str, FlagDefinition]) -> ParsedSubmissionCommand:
        parts = []
        for part in raw_command.strip().split():
            if part:
                parts.append(part)

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
                    flags.append(ParsedFlag(definition_name=None,token=raw_name,value=raw_value,raw_tokens=(token)))
                else:
                    flags.append(ParsedFlag(definition_name=None,token=token,value=None,raw_tokens=(token)))
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
                ParsedFlag(definition_name=definition.name,token=canonical_name,value=value,raw_tokens=tuple(raw_tokens)))
            index += 1
        
        return ParsedSubmissionCommand(executable=executable, flags=tuple(flags),positionals=tuple(positionals))

    # DO NOT DELETE THIS FUNCTION
    def canonical_name(self, token: str | None) -> str | None:
        if token is None:
            return None
        base = token.split("=", 1)[0].strip()
        return FLAG_BY_ALIAS.get(base, base)

    # DO NOT DELETE THIS FUNCTION
    def strip_provenance(self, parsed: ParsedSubmissionCommand) -> ParsedSubmissionCommand:
        filtered = []
        for flag in parsed.flags:
            token_canonical = self.canonical_name(flag.token)
            definition_canonical = self.canonical_name(flag.definition_name)

            if (token_canonical not in {"--provenance", "-p","-z", "--pythonpath"} and definition_canonical not in {"--provenance", "-p", "-z", "--pythonpath"}):
                filtered.append(flag)

        return ParsedSubmissionCommand(executable=parsed.executable,flags=tuple(filtered),positionals=parsed.positionals)

    # DO NOT DELETE THIS FUNCTION
    def strip_unsupported_for_backend(self,parsed: ParsedSubmissionCommand,backend: ExecutionBackend) -> ParsedSubmissionCommand:
        if backend != ExecutionBackend.LOCAL:
            return parsed
    
        filtered_flags = [
            flag
            for flag in parsed.flags
            if self.canonical_name(flag.token) not in SLURM_ONLY_FLAG_BASES
            and self.canonical_name(flag.definition_name) not in SLURM_ONLY_FLAG_BASES
        ]
        return ParsedSubmissionCommand(executable=parsed.executable, flags=tuple(filtered_flags),positionals=parsed.positionals)

    # DO NOT DELETE THIS FUNCTION
    def normalize_executable(self,parsed: ParsedSubmissionCommand, backend: ExecutionBackend, runtime_executable: str | None) -> ParsedSubmissionCommand:
        executable = runtime_executable or ("enqueue_compss" if backend == ExecutionBackend.SLURM else "runcompss")
        return ParsedSubmissionCommand(executable=executable,flags=parsed.flags,positionals=parsed.positionals)

    # DO NOT DELETE THIS FUNCTION
    def remap_paths(self, parsed: ParsedSubmissionCommand, crate_root: Path) -> ParsedSubmissionCommand:
        remapped_flags: list[ParsedFlag] = []
        for flag in parsed.flags:
            if flag.value is None:
                remapped_flags.append(flag)
            else:
                remapped_flags.append(ParsedFlag(definition_name=flag.definition_name, token=flag.token, value=self.remap_single_argument(flag.value, crate_root),raw_tokens=flag.raw_tokens))

        remapped_positionals = tuple(self.remap_single_argument(argument, crate_root) for argument in parsed.positionals)

        return ParsedSubmissionCommand( executable=parsed.executable, flags=tuple(remapped_flags), positionals=remapped_positionals )

    # DO NOT DELETE THIS FUNCTION
    def remap_single_argument(self, arg: str, crate_root: Path) -> str:
        had_trailing_slash = arg.endswith("/") and arg != "/"

        expanded = os.path.expanduser(arg)
        path = Path(expanded)

        if path.is_absolute():
            if path.exists():
                return arg

            candidates = self.candidate_local_paths(path, crate_root)
            for candidate in candidates:
                if candidate.exists():
                    return self._format_mapped_path(candidate, had_trailing_slash)
        else:
            candidates = self.candidate_relative_paths(path, crate_root)
            for candidate in candidates:
                if candidate.exists():
                    return self._format_mapped_path(candidate, had_trailing_slash)

        basename_matches = list(crate_root.rglob(path.name))
        if len(basename_matches) == 1 and basename_matches[0].exists():
            return self._format_mapped_path(basename_matches[0], had_trailing_slash)

        return arg


    def candidate_relative_paths(self, original: Path, crate_root: Path) -> list[Path]:
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


    def candidate_local_paths(self, original: Path, crate_root: Path) -> list[Path]:
        parts = list(original.parts)

        anchors = ("application_sources","dataset","datasets","data","src")

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


    # DO NOT DELETE THIS FUNCTION
    def discover_command(self, crate_root: Path) -> str | None:
        # crate_root is now passed directly as an argument, no need to extract from crate
    
        for path in [crate_root / "compss_submission_command_line.txt", *sorted(crate_root.rglob("compss_submission_command_line.txt"))]:
            if path.is_file():
                first_line = path.read_text(encoding="utf-8").splitlines()
                if first_line:
                    command = self.normalize_submission_command(first_line[0])
                    if command:
                        return command
    
        rocrate = self.load_rocrate(crate_root)
        if rocrate:
            command = self.extract_command_from_rocrate(rocrate)
            if command:
                return command
    
        return None


    # DO NOT DELETE THIS FUNCTION
    def load_rocrate(self, crate_root: Path) -> ROCrate | None:
        try:
            return ROCrate(crate_root)
        except Exception:
            return None

    # DO NOT DELETE THIS FUNCTION
    def extract_command_from_rocrate(self, crate: ROCrate) -> str | None:
        create_action = self.get_create_action_of_submission_command(crate)
        if create_action:
            command = create_action.get("description")
            return command
        return None

    # DO NOT DELETE THIS FUNCTION
    def get_create_action_of_submission_command(self, crate: ROCrate) -> dict | None:
        for entity in crate.get_entities():
            raw_type = entity.get("@type")
            if raw_type == "CreateAction":
                entity_id = entity.id
                if entity_id.startswith("#COMPSs_"):
                    return entity
        return None

    
    # DO NOT DELETE THIS FUNCTION
    def normalize_submission_command(self, value: object) -> str | None:
        text = value.strip()
        for prefix in COMMAND_PREFIXES:
            if text == prefix or text.startswith(prefix + " "):
                return text
        return None

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

    def apply_submission_edits(self, parsed: ParsedSubmissionCommand, edits: tuple[SubmissionCommandEdit, ...]) -> ParsedSubmissionCommand:
        flags = list(parsed.flags)
    
        for edit in edits:
            canonical_name = self.canonical_name(edit.name)
    
            if edit.kind == SubmissionCommandEditKind.REMOVE:
                flags = [
                    flag
                    for flag in flags
                    if self.canonical_name(flag.definition_name or flag.token) != canonical_name
                ]
                continue
    
            replacement = ParsedFlag(definition_name=canonical_name if self.resolve_flag_definition(canonical_name) else None, token=canonical_name or edit.name, value=edit.value, raw_tokens=())
    
            matching_indexes = [
                index
                for index, flag in enumerate(flags)
                if self.canonical_name(flag.definition_name or flag.token) == canonical_name
            ]
    
            if matching_indexes:
                first_index = matching_indexes[0]
                flags[first_index] = replacement
                flags = [
                    flag
                    for index, flag in enumerate(flags)
                    if index == first_index or index not in matching_indexes
                ]
            else:
                flags.append(replacement)
    
        return ParsedSubmissionCommand(executable=parsed.executable,flags=tuple(flags),positionals=parsed.positionals)