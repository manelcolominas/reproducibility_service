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

from rich.console import Console
from rich.panel import Panel
from rich.progress import Progress, SpinnerColumn, TextColumn
from rich.prompt import Confirm, Prompt
from rich.table import Table
from rich.text import Text

from InquirerPy import inquirer
import questionary


from application.ports.executor import ExecutionOutcome
from application.use_cases.import_crate import ImportCrateResult
from application.use_cases.inspect_crate import InspectCrateResult
from application.use_cases.prepare_provenance import PrepareProvenanceResult
from application.use_cases.verify_inputs import VerifyInputsResult
from domain.models.crate import CrateSummary
from domain.models.verification import VerificationState
from domain.models.execution import ExecutionPlan, ExecutionBackend

LOCAL_FLAG_OPTIONS = [
    ("--graph=<bool>", "Generation of the complete graph (true/false)"),
    ("--graph", "Enable graph generation shortcut"),
    ("--tracing", "Set generation of traces."),
    ("--tracing=<value>", "Set generation of traces."),
    ("--monitoring=<int>", "Period between monitoring samples in (milliseconds)"),
    ("--monitoring", "Enable monitoring"),
    ("--external_debugger=<int>", "Enables external debugger connection on the specified port (or 9999 if empty)"),
    ("--external_debugger", "Enables external debugger connection on the default port 9999"),
    ("--jmx_port=<int>","Enable JVM profiling on specified port"),
    ("--task_execution=<compss|storage>", "Task execution under COMPSs or Storage. Default: compss"),
    ("--storage_impl=<string>", "Path to an storage implementation. Shortcut to setting pypath and classpath. See Runtime/storage in your installation folder."),
    ("--storage_conf=<path>", "Path to the storage configuration file"),
    ("--provenance=<yaml_file>", "Generate COMPSs workflow provenance data in RO-Crate format using a YAML configuration file. Automatically activates --graph."),
    ("--provenance", "Generate COMPSs workflow provenanºce data in RO-Crate format using a YAML configuration file. Automatically activates --graph.")
]

SLURM_FLAG_OPTIONS = [
    ("--sc_cfg=<name>", "Scheduler configuration name"),
    ("--exec_time=<minutes>", "Execution time limit in minutes"),
    ("--job_name=<name>", "SLURM job name"),
    ("--queue=<name>", "Target SLURM queue"),
]

console = Console()


def print_banner() -> None:
    console.print(
        Panel(
            Text("COMPSs Reproducibility Service", style="bold cyan", justify="center"),
            subtitle="reproduce a COMPSs workflow run from an RO-Crate",
            border_style="cyan",
        )
    )


def print_error(message: str, details: str | None = None) -> None:
    body = message if not details else f"{message}\n[dim]{details}[/dim]"
    console.print(Panel(body, title="Error", border_style="red", title_align="left"))


def print_import_result(result: ImportCrateResult) -> None:
    table = Table.grid(padding=(0, 1))
    table.add_row("Source kind", result.source.kind.value)
    table.add_row("Source value", result.source.value)
    table.add_row("Working path", str(result.location.working_path))
    if result.acquisition is not None:
        acquisition_kind = _first_true(
            copied=result.acquisition.copied,
            extracted=result.acquisition.extracted,
            downloaded=result.acquisition.downloaded,
        )
        table.add_row("Acquisition", acquisition_kind)
    console.print(Panel(table, title="1. Crate source imported", border_style="green", title_align="left"))


def print_inspect_result(result: InspectCrateResult, crate: CrateSummary | None) -> None:
    if crate is None:
        print_error("Could not extract usable metadata from the crate")
        return

    table = Table.grid(padding=(0, 1))
    table.add_row("Name", crate.metadata.name)
    table.add_row("Description", crate.metadata.description or "[dim]-[/dim]")
    table.add_row("License", crate.metadata.license or "[dim]-[/dim]")
    table.add_row("Data persistence", crate.metadata.data_persistence.value)
    table.add_row("Authors", str(len(crate.metadata.authors)))
    table.add_row("Sources", str(len(crate.index.sources)))
    console.print(Panel(table, title="2. Metadata inspected", border_style="green", title_align="left"))

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
        f"  {summary.verified}/{summary.total} verified, "
        f"{summary.failed} failed, {summary.warnings} warnings\n"
    )


def print_execution_plan(plan: ExecutionPlan) -> None:
    table = Table.grid(padding=(0, 1))
    table.add_row("Backend", plan.backend.value)
    table.add_row("Command", plan.command.as_string())
    table.add_row("Run directory", str(plan.context.run_directory))
    table.add_row("Provenance", "enabled" if plan.provenance_enabled else "disabled")
    console.print(Panel(table, title="4. Execution plan", border_style="green", title_align="left"))


def print_provenance_result(result: PrepareProvenanceResult) -> None:
    if result.created_metadata_file:
        console.print(
            Panel(
                f"Provenance metadata written to:\n{result.created_metadata_file}",
                title="Provenance",
                border_style="green",
                title_align="left",
            )
        )
    elif result.warnings:
        for warning in result.warnings:
            console.print(f"  [yellow]![/yellow] {warning}")


def run_with_spinner(description: str, fn, *args, **kwargs):
    with Progress(
        SpinnerColumn(), TextColumn("[progress.description]{task.description}"), console=console, transient=True,
    ) as progress:
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


# with InquirerPy, the checkbox prompt does not support dynamic input for flags with placeholders, so we need to resolve them after selection. The following function is commented out because it was replaced by a version using questionary, which allows for better handling of user input.
# def select_submission_flags(backend: ExecutionBackend) -> list[str]:
#     options = LOCAL_FLAG_OPTIONS if backend == ExecutionBackend.LOCAL else SLURM_FLAG_OPTIONS

#     selected = inquirer.checkbox(
#         message=f"Select {backend.value.upper()} submission flags",
#         choices=[
#             {"name": f"{flag} - {description}", "value": flag}
#             for flag, description in options
#         ],
#         instruction="Use arrow keys to move, space to select, enter to confirm",
#     ).execute()

#     return [_resolve_flag_value(flag) for flag in selected]


def select_submission_flags(
    backend: ExecutionBackend,
    current_command: list[str] | None = None,
) -> list[str] | None:
    options = LOCAL_FLAG_OPTIONS if backend == ExecutionBackend.LOCAL else SLURM_FLAG_OPTIONS
    active_bases = _active_flags(current_command)

    selected = questionary.checkbox(
        f"Select {backend.value.upper()} submission flags",
        choices=[
            questionary.Choice(
                title=f"{flag} - {description}",
                value=flag,
                checked= flag in active_bases,
            )
            for flag, description in options
        ],
        instruction="Use arrow keys to move, space to select, enter to confirm",
    ).ask()

    if selected is None:
        return None

    return [_resolve_flag_value(flag) for flag in selected]


def _active_flags(current_command: list[str] | None) -> set[str]:
    if not current_command:
        return set()

    return {part for part in current_command[1:] if part.startswith("--")}


def _resolve_flag_value(template: str) -> str:
    if "<" not in template or ">" not in template:
        return template

    placeholder = template[template.index("<") + 1:template.index(">")]
    value = Prompt.ask(f"[yellow]Value for {template} ({placeholder})[/yellow]").strip()
    return template.replace(f"<{placeholder}>", value)