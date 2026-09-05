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
from rich.live import Live

import questionary

from application.use_cases.inspect_crate import InspectCrateResult
from application.use_cases.import_crate import ImportCrateResult
from application.use_cases.prepare_provenance import PrepareProvenanceResult
from domain.models.crate import EntityKind
from domain.models.execution import ExecutionPlan, ExecutionBackend, ExecutionOutcome

from application.use_cases.build_execution_plan import (
    SubmissionCommandEdit,
    SubmissionCommandEditKind
)

PROVENANCE_FLAGS = {"--provenance", "-p"}

# Create a single console instance from Rich library to be used throughout the module for rendering output.
console = Console()

from application.use_cases.flags import (
    canonical_flag_base,
    _resolve_flag_definition,
    _flag_requires_value,
    _validate_flag_value,
    extract_current_flags,
    available_flag_choices
)

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
    console.print(Panel(table, title="1. Crate source imported", border_style="green", title_align="left"))

def print_inspect_result(result, submission_command: str | None = None) -> None:
    crate = result.import_crate_result
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
    table.add_row("Data persistence","[green]true[/green]" if crate.data_persistence.value == "true" else f"[red]{crate.data_persistence.value}[/red]")

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
            
def print_verification_table(inspect_crate_result: InspectCrateResult) -> None:
    table = Table(title="3. Input verification", show_lines=False)
    table.add_column("Entity")
    table.add_column("Type")
    # table.add_column("Size (bytes)")
    table.add_column("Exists")
    table.add_column("Path")

    for item in inspect_crate_result.import_crate_result.workflow_metadata.workflow_entity_summary.entities:
        style = "green" if item.exists else "red"
        if item.exists:
            item_exists_row_value = "Exists"
            style = "green"
        elif item.type in {EntityKind.SOFTWARE_SOURCE_CODE, EntityKind.INPUT_OR_OUTPUT}:
            item_exists_row_value = "Missing"
            style = "red"
        else:
            item_exists_row_value = "Warning"
            style = "yellow"

        table.add_row(
            item.name,
            item.type.value,
            # str(item.size_bytes),
            f"[{style}]{item_exists_row_value}[/{style}]",
            str(item.path or ""),
        )

    console.print(table)
    workflow_entity_summary = inspect_crate_result.import_crate_result.workflow_metadata.workflow_entity_summary
    console.print(
        f"{workflow_entity_summary.total} checked"
        f", {workflow_entity_summary.total_success} succeeded"
        f", {workflow_entity_summary.total_failed} failed"
        f", {workflow_entity_summary.total_warnings} warnings\n"
    )

# DO NOT DELETE THIS FUNCTION
def print_questionary_edit_submission_command( backend: ExecutionBackend, current_command: list[str] | None = None) -> list[SubmissionCommandEdit] | None:
    current_flags = sort_flag_choices(extract_current_flags(current_command))

    executable = current_command[0] if current_command else "runcompss"
    edits: list[SubmissionCommandEdit] = []

    while True:
        action = questionary.select(
            "What do you want to do?", choices=[ "remove a flag", "edit a flag value", "add a new flag","finish"]).ask()

        if action is None:
            return None

        if action == "finish":
            break

        if action == "remove a flag":
            if not current_flags:
                console.print("[yellow]No flags available to remove.[/yellow]")
                continue
            remove_choices = [*sort_flag_choices(current_flags), "back"]
            flag = questionary.select("Choose a flag to remove", choices=remove_choices).ask()
            if flag is None or flag == "back":
                continue
            edits.append(SubmissionCommandEdit(kind=SubmissionCommandEditKind.REMOVE,name=flag.split("=", 1)[0],value=None))
            current_flags.remove(flag)
            print_edited_submission_command(executable, current_flags)

        elif action == "edit a flag value":
            if not current_flags:
                console.print("[yellow]No flags available to edit.[/yellow]")
                continue

            edit_choices = [*sort_flag_choices(current_flags), "back"]
            flag = questionary.select("Choose a flag to edit", choices=edit_choices).ask()
            if flag is None or flag == "back":
                continue

            flag_name = canonical_flag_base(flag)
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

            edits.append(SubmissionCommandEdit(kind=SubmissionCommandEditKind.SET_VALUE,name=flag_name,value=value))
            updated_flag = flag_name if value is None else f"{flag_name}={value}"

            current_flags = [current_flag for current_flag in current_flags if canonical_flag_base(current_flag) != canonical_flag_base(flag)]
            current_flags.append(updated_flag)
            current_flags = sort_flag_choices(current_flags)

            print_edited_submission_command(executable, current_flags)

        elif action == "add a new flag":
            choices = available_flag_choices(backend, current_flags)
            if not choices:
                console.print("[yellow]No flags available to add.[/yellow]")
                continue

            choices = sorted(choices,key=lambda choice: canonical_flag_base(choice.split(" - ", 1)[0]).casefold())
            add_choices = [*choices, "back"]
            selected = questionary.select("Choose a flag to add", choices=add_choices).ask()
            if selected is None or selected == "back":
                continue

            flag_spec = selected.split(" - ", 1)[0]
            flag_name = canonical_flag_base(flag_spec)

            definition = _resolve_flag_definition(flag_name)
            if definition is None:
                console.print(f"[red]Unknown flag: {flag_name}[/red]")
                continue

            if canonical_flag_base(flag_name) in {canonical_flag_base(flag) for flag in current_flags}:
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

            edits.append(SubmissionCommandEdit(kind=SubmissionCommandEditKind.ADD,name=flag_name,value=value))

            new_item = flag_name if value is None else f"{flag_name}={value}"
            current_flags = [
                f for f in current_flags
                if canonical_flag_base(f) != canonical_flag_base(new_item)
            ]
            current_flags.append(new_item)
            print_edited_submission_command(executable,current_flags)

    return edits

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

# def run_with_spinner(description: str, fn, *args, **kwargs):
#     """
#     """
#     with Progress(SpinnerColumn(), TextColumn("[progress.description]{task.description}"), console=console, transient=True) as progress:
#         progress.add_task(description, total=None)
#         return fn(*args, **kwargs)


def run_with_spinner(description: str, fn, *args, **kwargs):
    progress = Progress(SpinnerColumn(style="bold cyan"), TextColumn("[bold cyan]{task.description}"), console=console, auto_refresh=False)

    panel = Panel(progress, title="Working", subtitle="Please wait", border_style="cyan", padding=(1, 3),expand=True)

    with Live(panel, console=console, refresh_per_second=12):
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

    console.print(Panel(table, title="5. Execution summary", border_style=status_style, title_align="left"))

def print_edited_submission_command(executable: str,flags: list[str]) -> None:
    command = " ".join([executable, *flags])
    console.print()
    console.print("[cyan]Edited submission command:[/cyan]")
    console.print(f"  {command}")
    console.print()

def sort_flag_choices(flags: list[str]) -> list[str]:
    return sorted(flags,key=lambda flag: canonical_flag_base(flag).casefold())