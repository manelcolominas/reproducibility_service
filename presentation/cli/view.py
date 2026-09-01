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

"""Rich rendering helpers for the reproducibility service CLI.

Every function here only renders things (panels, tables, prompts). None of
them make decisions or call use cases — that logic lives in app.py so the
view stays trivially testable/replaceable.
"""

from __future__ import annotations

from rich.console import Console, Group
from rich.panel import Panel
from rich.progress import Progress, SpinnerColumn, TextColumn
from rich.prompt import Prompt
from rich.table import Table
from rich.text import Text

import questionary

from application.ports.executor import ExecutionOutcome
from application.use_cases.inspect_crate import InspectCrateResult
from application.use_cases.import_crate import ImportCrateResult
from application.use_cases.prepare_provenance import PrepareProvenanceResult
from domain.models.execution import ExecutionPlan, ExecutionBackend

from application.use_cases.build_execution_plan import (
    SubmissionCommandEdit,
    SubmissionCommandEditKind,
    FlagValueKind,
    FLAG_DEFINITIONS,
    build_flag_options
)

LOCAL_FLAG_OPTIONS = build_flag_options(ExecutionBackend.LOCAL)
SLURM_FLAG_OPTIONS = build_flag_options(ExecutionBackend.SLURM)

PROVENANCE_FLAGS = {"--provenance", "-p"}

FLAG_CANONICAL_MAP = {
"-p": "--provenance",
"-d": "--debug",
"-z": "--zip_provenance",
}

# Create a single console instance from Rich library to be used throughout the module for rendering output.
console = Console()

def _option_takes_value(flag_spec: str) -> bool:
    return "=" in flag_spec

def _canonical_flag_base(flag: str) -> str:
    raw = (flag or "").split("=", 1)[0].split(" - ", 1)[0].strip()
    return FLAG_CANONICAL_MAP.get(raw, raw)

LOCAL_FLAG_BASES = {_canonical_flag_base(flag) for flag, _ in LOCAL_FLAG_OPTIONS}
SLURM_FLAG_BASES = {_canonical_flag_base(flag) for flag, _ in SLURM_FLAG_OPTIONS}
SLURM_ONLY_FLAG_BASES = SLURM_FLAG_BASES - LOCAL_FLAG_BASES
VALUE_FLAG_BASES = {_canonical_flag_base(flag) for flag, _ in (LOCAL_FLAG_OPTIONS + SLURM_FLAG_OPTIONS) if _option_takes_value(flag)}

def edit_submission_command(
    backend: ExecutionBackend,
    current_command: list[str] | None = None,
) -> list[SubmissionCommandEdit] | None:
    current_flags = _extract_current_flags(current_command)
    edits: list[SubmissionCommandEdit] = []

    while True:
        action = questionary.select(
            "What do you want to do?",
            choices=[
                "remove a flag",
                "edit a flag value",
                "add a new flag",
                "finish",
            ],
        ).ask()

        if action is None:
            return None

        if action == "finish":
            break

        if action == "remove a flag":
            if not current_flags:
                console.print("[yellow]No flags available to remove.[/yellow]")
                continue
            flag = questionary.select("Choose a flag to remove", choices=current_flags).ask()
            if flag is None:
                continue
            edits.append(
                SubmissionCommandEdit(
                    kind=SubmissionCommandEditKind.REMOVE,
                    name=flag.split("=", 1)[0],
                    value=None,
                )
            )
            current_flags.remove(flag)

        elif action == "edit a flag value":
            if not current_flags:
                console.print("[yellow]No flags available to edit.[/yellow]")
                continue

            flag = questionary.select("Choose a flag to edit", choices=current_flags).ask()
            if flag is None:
                continue

            flag_name = _canonical_flag_base(flag)
            definition = _resolve_flag_definition(flag_name)

            if definition is None:
                console.print(f"[red]Unknown flag: {flag_name}[/red]")
                continue

            value = ""
            while True:
                raw_value = Prompt.ask(f"New value for {flag_name}").strip()
                try:
                    value = _validate_flag_value(flag_name, raw_value)
                    break
                except ValueError as exc:
                    console.print(f"[yellow]{exc}[/yellow]")

            edits.append(
                SubmissionCommandEdit(
                    kind=SubmissionCommandEditKind.SET_VALUE,
                    name=flag_name,
                    value=value,
                )
            )

        elif action == "add a new flag":
            choices = _available_flag_choices(backend, current_flags)
            if not choices:
                console.print("[yellow]No flags available to add.[/yellow]")
                continue

            selected = questionary.select("Choose a flag to add", choices=choices).ask()
            if selected is None:
                continue

            flag_spec = selected.split(" - ", 1)[0]
            flag_name = _canonical_flag_base(flag_spec)

            definition = _resolve_flag_definition(flag_name)
            if definition is None:
                console.print(f"[red]Unknown flag: {flag_name}[/red]")
                continue

            if _canonical_flag_base(flag_name) in {_canonical_flag_base(flag) for flag in current_flags}:
                console.print(f"[yellow]Flag already present: {flag_name}[/yellow]")
                continue

            value = None
            if _flag_requires_value(flag_name):
                while True:
                    raw_value = Prompt.ask(f"Value for {flag_name}").strip()
                    try:
                        value = _validate_flag_value(flag_name, raw_value)
                        break
                    except ValueError as exc:
                        console.print(f"[yellow]{exc}[/yellow]")
            else:
                value = None

            edits.append(
                SubmissionCommandEdit(
                    kind=SubmissionCommandEditKind.ADD,
                    name=flag_name,
                    value=value,
                )
            )

            new_item = flag_name if value is None else f"{flag_name}={value}"
            current_flags = [
                f for f in current_flags
                if _canonical_flag_base(f) != _canonical_flag_base(new_item)
            ]
            current_flags.append(new_item)

    return edits

def _available_flag_choices(backend: ExecutionBackend, current_flags: list[str]) -> list[str]:
    available = LOCAL_FLAG_OPTIONS if backend == ExecutionBackend.LOCAL else SLURM_FLAG_OPTIONS
    current_bases = {_canonical_flag_base(flag) for flag in current_flags}
    choices: list[str] = []

    for flag_spec, description in available:
        base = _canonical_flag_base(flag_spec)
        if base in current_bases:
            continue

        definition = _resolve_flag_definition(base)
        if definition is not None and backend not in definition.backend_scope:
            continue

        choices.append(f"{flag_spec} - {description}")

    return choices

def print_banner() -> None:
    console.print(
        # creates a Panel object of the rich library, which is a box with a border and a title. 
        # The content of the panel is a Text object that contains the text "COMPSs Reproducibility Service"
        # in bold cyan color and centered. The panel also has a subtitle that says "reproduce a COMPSs workflow run from an RO-Crate"
        # and a cyan border style.
        Panel(
            Text("COMPSs Reproducibility Service", style="bold cyan", justify="center"),
            subtitle="reproduce a COMPSs workflow run from an RO-Crate",
            border_style="cyan",
        )
    )
    # and then it prints it on the console using the console.print() method.

def print_error(message: str, details: str | None = None) -> None:
    body = message if not details else f"{message}\n[dim]{details}[/dim]"
    console.print(Panel(body, title="Error", border_style="red", title_align="left"))

def print_import_result(result: ImportCrateResult) -> None:
    table = Table.grid(padding=(0, 1))
    table.add_row("Source type", result.source.type.value)
    table.add_row("Source name", result.source.name)
    table.add_row("Ro-Crate path", str(result.crate_location))
    if result.acquisition is not None:
        table.add_row("Acquisition", result.acquisition.kind)
    console.print(
        Panel(table, title="1. Crate source imported", border_style="green", title_align="left")
    )

def print_inspect_result(result: InspectCrateResult,  | None, submission_command: str | None = None) -> None:
    if crate is None:
        print_error("Could not extract usable metadata from the crate")
        return

    table = Table.grid(padding=(0, 1))
    table.add_column(style="bold cyan", no_wrap=True)
    table.add_column(style="white")
    table.add_row(
        "Submission command",
        submission_command or "[dim]not resolved yet[/dim]",
    )
    table.add_row("Data persistence","[green]true[/green]" if crate.metadata.data_persistence.value == "true" else f"[red]{crate.metadata.data_persistence.value}[/red]")

    body = table
    if result.inspect_output:
        body = Group(Text.from_ansi(result.inspect_output.rstrip()),table)

    console.print(
        Panel(
            body,
            title="[bold green]2. Metadata inspected[/bold green]",
            border_style="green",
            title_align="left"
        )
    )

    if result.warnings:
        for warning in result.warnings:
            console.print(f"  [yellow]![/yellow] {warning}")
            
def print_verification_table(result: VerifyInputsResult) -> None:
    table = Table(title="3. Input verification", show_lines=False)
    table.add_column("Artifact")
    table.add_column("State")
    table.add_column("Path")

    for item in result.summary.items:
        style = "green" if item.state == VerificationState.VERIFIED else "red"
        table.add_row(
            item.reference.metadata_name,
            f"[{style}]{item.state.value}[/{style}]",
            str(item.resolved_path or ""),
        )

    console.print(table)
    summary = result.summary
    console.print(
        f"{summary.verified}/{summary.total} verified"
        f"{summary.failed} failed, {summary.warnings} warnings\n"
    )

def print_execution_plan(plan: ExecutionPlan) -> None:
    table = Table.grid(padding=(0, 1))
    table.add_row("Backend", plan.backend.value)
    table.add_row("Submission Command", plan.command.as_string())
    table.add_row("Execution directory", str(plan.context.execution_directory))
    table.add_row("Workspace directory", str(plan.context.workspace_directory))
    table.add_row("Provenance", "enabled" if plan.provenance_enabled else "disabled")
    console.print(Panel(table, title="4. Execution plan", border_style="green", title_align="left"))

def print_provenance_result(result: PrepareProvenanceResult) -> None:
    if result.provenance_config_file:
        console.print(
            Panel(
                f"Provenance config file will be written to:\n{result.provenance_config_file}",
                title="Provenance",
                border_style="green",
                title_align="left",
            )
        )
    elif result.warnings:
        for warning in result.warnings:
            console.print(f"  [yellow]![/yellow] {warning}")

def run_with_spinner(description: str, fn, *args, **kwargs):
    """
    """
    with Progress(SpinnerColumn(), TextColumn("[progress.description]{task.description}"), console=console, transient=True) as progress:
        progress.add_task(description, total=None)
        return fn(*args, **kwargs)

def print_final_summary(outcome: ExecutionOutcome) -> None:
    status_style = "green" if outcome.succeeded else "red"
    status_text = "SUCCEEDED" if outcome.succeeded else "FAILED"

    table = Table.grid(padding=(0, 1))
    table.add_row("Status", f"[{status_style}]{status_text}[/{status_style}]")
    table.add_row("Return code", str(outcome.result.return_code))
    table.add_row("Stdout log", str(outcome.result.log.stdout_path))
    table.add_row("Stderr log", str(outcome.result.log.stderr_path))
    table.add_row("Results directory", str(outcome.submission.results_directory))
    if outcome.result.generated_ro_crate_path is not None:
        table.add_row("Generated RO-Crate artifact at", str(outcome.result.generated_ro_crate_path))
    if outcome.result.error_message:
        table.add_row("Error", outcome.result.error_message)

    console.print(
        Panel(table, title="5. Execution summary", border_style=status_style, title_align="left")
    )

def _first_true(**flags: bool) -> str:
    for name, value in flags.items():
        if value:
            return name
    return "unknown"

def _flag_base(flag: str) -> str:
    return _canonical_flag_base(flag)

def _resolve_flag_definition(flag_name: str):
    base = _canonical_flag_base(flag_name)
    for flag in FLAG_DEFINITIONS:
        if base == flag.name or base in flag.aliases:
            return flag
    return None

def _flag_requires_value(flag_name: str) -> bool:
    definition = _resolve_flag_definition(flag_name)
    if definition is None:
        return False
    return definition.value_kind != FlagValueKind.NONE

def _validate_flag_value(flag_name: str, value: str) -> str:
    definition = _resolve_flag_definition(flag_name)
    if definition is None:
        return value

    if definition.value_kind == FlagValueKind.NONE:
        raise ValueError(f"Flag {flag_name} does not accept a value")

    if definition.value_kind == FlagValueKind.BOOL:
        normalized = value.lower()
        if normalized not in {"true", "false"}:
            raise ValueError(f"Flag {flag_name} expects a boolean value: true/false")
        return normalized

    if definition.value_kind == FlagValueKind.INT:
        try:
            int(value)
            return value
        except ValueError as exc:
            raise ValueError(f"Flag {flag_name} expects an integer value") from exc

    return value

def _extract_current_flags(current_command: list[str] | None) -> list[str]:
    if not current_command:
        return []

    extracted: list[str] = []
    seen_bases: set[str] = set()
    index = 1

    while index < len(current_command):
        token = current_command[index]

        if not token.startswith("-"):
            index += 1
            continue

        if token in PROVENANCE_FLAGS:
            index += 1
            continue

        if "=" in token:
            flag = token
            index += 1
        elif (
            _flag_base(token) in VALUE_FLAG_BASES
            and index + 1 < len(current_command)
            and not current_command[index + 1].startswith("-")
        ):
            flag = f"{token}={current_command[index + 1]}"
            index += 2
        else:
            flag = token
            index += 1

        canonical_base = _canonical_flag_base(flag)
        if canonical_base == "--provenance":
            continue

        if canonical_base not in seen_bases:
            extracted.append(flag)
            seen_bases.add(canonical_base)

    return extracted
