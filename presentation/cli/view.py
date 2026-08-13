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
    ("--project=<path>", "Path to the COMPSs project file"),
    ("--resources=<path>", "Path to the COMPSs resources file"),
    ("--socket=<string>", "Socket name for the COMPSs runtime"),
    ("--lang=<name>", "Language for the COMPSs runtime"),
    ("--summary", "Print a summary of the COMPSs execution"),
    ("--log_level=<level>", "Set the log level for the COMPSs runtime"),
    ("--debug", "Enable debug mode for the COMPSs runtime"),
    ("-d", "Enable debug mode for the COMPSs runtime"),
    ("--extrae_config_file=<path>", "Path to the Extrae configuration file"),
    ("--extrae_config_file_python=<path>", "Path to the Extrae configuration file for Python"),
    ("--trace_label=<string>", "Label for the generated trace"),
    ("--tracing_task_dependencies=<bool>", "Enable tracing of task dependencies (true/false)"),
    ("--generate_trace=<bool>", "Enable tracing of task dependencies"),
    ("--delete_trace_packages=<bool>", "Delete trace packages after execution (true/false)"),
    ("--custom_threads=<bool>", "Enable custom threads for the COMPSs runtime (true/false)"),
    ("--comm=<ClassName>", "Communication implementation class name for the COMPSs runtime"),
    ("--conn=<className>", "Connection implementation class name for the COMPSs runtime"),
    ("--streaming=<type>", "Enable streaming for the COMPSs runtime (type: TCP, UDP, etc.)"),
    ("--streaming_master_name=<str>", "Master name for the streaming implementation"),
    ("--streaming_master_port=<int>", "Master port for the streaming implementation"),
    ("--scheduler=<className>", "Scheduler implementation class name for the COMPSs runtime"),
    ("--scheduler_config_file=<path>", "Path to the scheduler configuration file"),
    ("--checkpoint=<className>", "Checkpoint implementation class name for the COMPSs runtime"),
    ("--checkpoint_params=<string>", "Parameters for the checkpoint implementation"),
    ("--checkpoint_folder=<path>", "Folder for storing checkpoints"),
    ("--library_path=<path>", "Path to the library for the COMPSs runtime"),
    ("--classpath=<path>", "Path to the classpath for the COMPSs runtime"),
    ("--appdir=<path>", "Path to the application directory for the COMPSs runtime"),
    #("--pythonpath=<path>", "Path to the Python path for the COMPSs runtime"),
    ("--env_script=<path>", "Path to the environment script for the COMPSs runtime"),
    ("--log_dir=<path>", "Path to the log directory for the COMPSs runtime"),
    ("--master_working_dir=<path>", "Path to the master working directory for the COMPSs runtime"),
    ("--uuid=<int>", "UUID for the COMPSs runtime"),
    ("--master_name=<string>", "Master name for the COMPSs runtime"),
    ("--master_port=<int>", "Master port for the COMPSs runtime"),
    ("--jvm_master_opts=<string>", "JVM options for the master process of the COMPSs runtime"),
    ("--jvm_workers_opts=<string>", "JVM options for the worker processes of the COMPSs runtime"),
    ("--cpu_affinity=<string>", "CPU affinity for the COMPSs runtime"),
    ("--gpu_affinity=<string>", "GPU affinity for the COMPSs runtime"),
    ("--fpga_affinity=<string>", "FPGA affinity for the COMPSs runtime"),
    ("--fpga_reprogram=<string>", "FPGA reprogramming command for the COMPSs runtime"),
    ("--io_executors=<int>", "Number of I/O executors for the COMPSs runtime"),
    ("--task_count=<int>", "Number of tasks for the COMPSs runtime"),
    ("--input_profile=<path>", "Path to the input profile for the COMPSs runtime"),
    ("--output_profile=<path>", "Path to the output profile for the COMPSs runtime"),
    ("--PyObject_serialize=<bool>", "Enable or disable PyObject serialization (true/false)"),
    ("--persistent_worker_c=<bool>", "Enable or disable persistent worker for C tasks (true/false)"),
    ("--enable_external_adaptation=<bool>", "Enable or disable external adaptation (true/false)"),
    ("--gen_coredump", "Enable or disable core dump generation"),
    ("--keep_workingdir", "Keep the working directory after execution"),
    ("--python_interpreter=<string>", "Path to the Python interpreter for the COMPSs runtime"),
    ("--python_propagate_virtual_environment=<bool>", "Enable or disable propagation of the Python virtual environment (true/false)"),
    ("--python_mpi_worker=<bool>", "Enable or disable MPI worker for Python tasks (true/false)"),
    ("--python_memory_profile=<string>", "Enable or disable memory profiling for Python tasks (true/false)"),
    ("--python_cache_profiler=<bool>", "Enable or disable cache profiling for Python tasks (true/false)"),
    ("--wall_clock_limit=<int>", "Set the wall clock limit for the COMPSs runtime in seconds"),
    ("--shutdown_in_node_failure=<bool>", "Enable or disable shutdown in node failure (true/false)"),
    ("--provenance=<yaml_file>", "Generate COMPSs workflow provenance data in RO-Crate format using a YAML configuration file. Automatically activates --graph."),
    ("--provenance", "Generate COMPSs workflow provenanºce data in RO-Crate format using a YAML configuration file. Automatically activates --graph."),
    ("--provenance_folder=<path>", "Folder to store the generated provenance data in RO-Crate format"),
    ("--zip_provenance", "Generate a ZIP file containing the provenance data in RO-Crate format"),
    ("-z", "Generate a ZIP file containing the provenance data in RO-Crate format"),
]

SLURM_FLAG_OPTIONS = [
    ("--heterogeneous", "Enable heterogeneous execution"),
    ("--sc_cfg=<name>", "Scheduler configuration name"),
    ("--exec_time=<minutes>", "Execution time limit in minutes"),
    ("--job_name=<name>", "SLURM job name"),
    ("--queue=<name>", "Target SLURM queue"),
    ("--reservation=<name>", "SLURM reservation name"),
    ("--job_execution_dir=<path>", "Directory for job execution"),
    ("--pre_env_script=<path/to/script>", "Path to a script to be executed before the environment script"),
    ("--extra_submit_flag=<flag>", "Extra flag to be passed to the SLURM submission command"),
    ("--storage_container_image=<string>", "Container image for the storage implementation"),
    ("--storage_cpu_affinity=<string>", "CPU affinity for the storage implementation"),
    ("--constraints=<constraints>", "Constraints for the SLURM job"),
    ("--project_name=<name>", "Project name for the SLURM job"),
    ("--qos=<qos>", "Quality of Service for the SLURM job"),
    ("--forward_cpus_per_node=<bool>", "Forward CPUs per node to the SLURM job (true/false)"),
    ("--job_dependency=<jobID> ", "Set a job dependency for the SLURM job"),
    ("--forward_time_limit=<true|false>", "Forward time limit to the SLURM job (true/false)"),
    ("--storage_home=<string>", "Storage home directory for the SLURM job"),
    ("--storage_props=<string>", "Storage properties for the SLURM job"),
    ("--participants=<string>", "Participants for the SLURM job"),
    ("--participants", "Participants for the SLURM job"),
    ("--num_nodes=<int>", "Number of nodes for the SLURM job"),
    ("--num_switches=<int>", "Number of switches for the SLURM job"),
    ("--type_cfg=<file_location>", "Type configuration file location for the SLURM job"),
    ("--master=<master_node_type>", "Master node type for the SLURM job"),
    ("--workers=type_X:nodes,type_Y:nodes", "Worker node types and counts for the SLURM job"),
    ("--cpus_per_node=<int>", "CPUs per node for the SLURM job"),
    ("--gpus_per_node=<int>", "GPUs per node for the SLURM job"),
    ("--fpgas_per_node=<int>", "FPGAs per node for the SLURM job"),
    ("--io_executors=<int>", "I/O executors per node for the SLURM job"),
    ("--fpga_reprogram=<string>", "FPGA reprogramming command for the SLURM job"),
    ("--max_tasks_per_node=<int>", "Maximum tasks per node for the SLURM job"),
    ("--node_memory=<MB>", "Node memory in MB for the SLURM job"),
    ("--node_storage_bandwidth=<MB>", "Node storage bandwidth in MB for the SLURM job"),
    ("--network=<name>", "Network type for the SLURM job"),
    ("--prolog=<string>", "Prolog script for the SLURM job"),
    ("--epilog=<string>", "Epilog script for the SLURM job"),
    ("--master_working_dir=<name | path>", "Master working directory for the SLURM job"),
    ("--worker_working_dir=<name | path>", "Worker working directory for the SLURM job"),
    ("--worker_in_master_cpus=<int>", "Number of worker CPUs in the master node for the SLURM job"),
    ("--worker_in_master_memory=<int>", "Amount of worker memory in the master node for the SLURM job"),
    ("--worker_port_range=<min>,<max>", "Port range for workers in the SLURM job"),
    ("--jvm_worker_in_master_opts=<string>", "JVM options for workers in the master node for the SLURM job"),
    ("--container_image=<path>", "Container image for the SLURM job"),
    ("--container_compss_path=<path>", "Path to COMPSs installation inside the container for the SLURM job"),
    ("--container_opts=<string>", "Extra options for the container execution in the SLURM job"),
    ("--elasticity=<max_extra_nodes>", "Maximum extra nodes for elasticity in the SLURM job"),
    ("--automatic_scaling=<bool>", "Enable or disable automatic scaling for the SLURM job (true/false)"),
    ("--jupyter_notebook=<path>", "Path to a Jupyter notebook to be executed in the SLURM job"),
    ("--jupyter_notebook", "Enable execution of a Jupyter notebook in the SLURM job"),
    ("--ipython", "Enable execution of an IPython shell in the SLURM job"),
    ("--ear=<bool|string>", "Enable or disable execution after recovery (true/false or path to recovery file)"),
]

console = Console()


def _option_flag_base(flag_spec: str) -> str:
    return flag_spec.split("=", 1)[0]

LOCAL_FLAG_BASES = {_option_flag_base(flag) for flag, _ in LOCAL_FLAG_OPTIONS}
SLURM_FLAG_BASES = {_option_flag_base(flag) for flag, _ in SLURM_FLAG_OPTIONS}
SLURM_ONLY_FLAG_BASES = SLURM_FLAG_BASES - LOCAL_FLAG_BASES

def _flag_base(flag: str) -> str:
    return flag.split("=", 1)[0]

def _filter_flags_for_backend(
    backend: ExecutionBackend,
    flags: list[str],
) -> tuple[list[str], list[str]]:
    if backend != ExecutionBackend.LOCAL:
        return flags, []

    kept: list[str] = []
    removed: list[str] = []
    for flag in flags:
        if _flag_base(flag) in SLURM_ONLY_FLAG_BASES:
            removed.append(flag)
        else:
            kept.append(flag)
    return kept, removed


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
    table.add_row("Source type", result.source.type.value)
    table.add_row("Source name", result.source.value)
    table.add_row("Copied/Downloaded Ro-Crate path", str(result.location.copied_downloaded_crate_path))
    if result.acquisition is not None:
        acquisition_type = _first_true(
            copied=result.acquisition.copied,
            extracted=result.acquisition.extracted,
            downloaded=result.acquisition.downloaded,
        )
        table.add_row("Acquisition", acquisition_type)
    console.print(Panel(table, title="1. Crate source imported", border_style="green", title_align="left"))


def print_inspect_result(result: InspectCrateResult, crate: CrateSummary | None) -> None:
    if crate is None:
        print_error("Could not extract usable metadata from the crate")
        return

    table = Table.grid(padding=(0, 1))
    table.add_row("Name", crate.metadata.name)
    table.add_row("Description", crate.metadata.description or "[dim]-[/dim]")
    table.add_row("COMPSs version", crate.metadata.compss_version or "[dim]-[/dim]")
    table.add_row("Executed at", crate.metadata.execution_site or "[dim]-[/dim]")
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


def select_submission_flags(
    backend: ExecutionBackend,
    current_command: list[str] | None = None,
) -> list[str] | None:
    current_flags = _extract_current_flags(current_command)
    choices: list[questionary.Choice] = [
        questionary.Choice(title=flag, value=flag, checked=True)
        for flag in current_flags
    ]

    add_pythonpath_choice = "__add_pythonpath__"
    can_offer_pythonpath = (
        backend == ExecutionBackend.LOCAL
        and not any(_flag_base(flag) == "--pythonpath" for flag in current_flags)
    )
    if can_offer_pythonpath:
        choices.append(
            questionary.Choice(
                title="Add --pythonpath",
                value=add_pythonpath_choice,
                checked=False,
            )
        )

    if not choices:
        console.print("[yellow]No submission flags found in the current command.[/yellow]")
        return []

    selected = questionary.checkbox(
        f"Select {backend.value.upper()} flags to keep (uncheck to remove)",
        choices=choices,
        instruction="Use arrow keys to move, space to toggle, enter to confirm",
    ).ask()

    if selected is None:
        return None

    final_flags = [flag for flag in selected if flag != add_pythonpath_choice]

    if add_pythonpath_choice in selected:
        pythonpath_value = Prompt.ask("Value for --pythonpath (path)").strip()
        if pythonpath_value:
            final_flags.append(f"--pythonpath={pythonpath_value}")

    return final_flags


def _flag_base(flag: str) -> str:
    return flag.split("=", 1)[0]


PROVENANCE_FLAGS = {"--provenance", "-p"}

def _extract_current_flags(current_command: list[str] | None) -> list[str]:
    if not current_command:
        return []

    extracted: list[str] = []
    seen: set[str] = set()
    index = 1

    while index < len(current_command):
        token = current_command[index]

        if not token.startswith("--"):
            index += 1
            continue

        if token in PROVENANCE_FLAGS:
            index += 1
            continue

        if "=" in token:
            flag = token
            index += 1
        elif index + 1 < len(current_command) and not current_command[index + 1].startswith("-"):
            flag = f"{token}={current_command[index + 1]}"
            index += 2
        else:
            flag = token
            index += 1

        if flag not in seen and _flag_base(flag) not in PROVENANCE_FLAGS:
            extracted.append(flag)
            seen.add(flag)

    return extracted
