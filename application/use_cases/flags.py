from enum import Enum
from dataclasses import dataclass

from application.use_cases.build_execution_plan import ExecutionBackend

# DO NOT DELETE THIS CLASS
class FlagValueKind(str, Enum):
    NONE = "none"
    BOOL = "bool"
    INT = "int"
    STRING = "string"
    PATH = "path"
    DIRECTORY = "directory"

# DO NOT DELETE THIS CLASS
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
    # LOCAL and SLURM shared flags
    FlagDefinition("--debug", "Enable debug mode for the COMPSs runtime.", (ExecutionBackend.LOCAL, ExecutionBackend.SLURM), aliases=("-d")),
    FlagDefinition("--pythonpath", "Path to Python modules for the COMPSs runtime.", (ExecutionBackend.LOCAL, ExecutionBackend.SLURM), FlagValueKind.PATH, prefer_equals=True),
    FlagDefinition("--log_level", "Set the log level for the COMPSs runtime.", (ExecutionBackend.LOCAL, ExecutionBackend.SLURM), FlagValueKind.STRING, prefer_equals=True),
    FlagDefinition("--lang", "Language for the COMPSs runtime.", (ExecutionBackend.LOCAL, ExecutionBackend.SLURM), FlagValueKind.STRING, prefer_equals=True),
    FlagDefinition("--graph", "Enable graph generation shortcut.", (ExecutionBackend.LOCAL, ExecutionBackend.SLURM), FlagValueKind.BOOL, prefer_equals=True),
    FlagDefinition("--tracing", "Set generation of traces.", (ExecutionBackend.LOCAL, ExecutionBackend.SLURM), FlagValueKind.STRING, prefer_equals=True),
    FlagDefinition("--monitoring", "Period between monitoring samples in (milliseconds).", (ExecutionBackend.LOCAL, ExecutionBackend.SLURM), FlagValueKind.INT, prefer_equals=True),
    FlagDefinition("--external_debugger", "Enables external debugger connection on the specified port (or 9999 if empty).", (ExecutionBackend.LOCAL, ExecutionBackend.SLURM), FlagValueKind.INT, prefer_equals=True),
    FlagDefinition("--jmx_port", "Enable JVM profiling on specified port.", (ExecutionBackend.LOCAL, ExecutionBackend.SLURM), FlagValueKind.INT, prefer_equals=True),
    FlagDefinition("--task_execution", "Task execution under COMPSs or Storage. Default: compss", (ExecutionBackend.LOCAL, ExecutionBackend.SLURM), FlagValueKind.STRING, prefer_equals=True),
    FlagDefinition("--storage_impl", "Path to an storage implementation. Shortcut to setting pypath and classpath. See Runtime/storage in your installation folder.", (ExecutionBackend.LOCAL,), FlagValueKind.STRING, prefer_equals=True),
    FlagDefinition("--storage_conf", "Path to the storage configuration file.", (ExecutionBackend.LOCAL, ExecutionBackend.SLURM), FlagValueKind.PATH, prefer_equals=True),
    FlagDefinition("--project", "Path to the COMPSs project file.", (ExecutionBackend.LOCAL, ExecutionBackend.SLURM), FlagValueKind.PATH, prefer_equals=True),
    FlagDefinition("--resources", "Path to the COMPSs resources file.", (ExecutionBackend.LOCAL, ExecutionBackend.SLURM), FlagValueKind.PATH, prefer_equals=True),
    FlagDefinition("--socket", "Socket name for the COMPSs runtime.", (ExecutionBackend.LOCAL, ExecutionBackend.SLURM), FlagValueKind.STRING, prefer_equals=True),
    FlagDefinition("--summary", "Print a summary of the COMPSs execution.", (ExecutionBackend.LOCAL, ExecutionBackend.SLURM), FlagValueKind.NONE),
    FlagDefinition("--extrae_config_file", "Path to the Extrae configuration file.", (ExecutionBackend.LOCAL, ExecutionBackend.SLURM), FlagValueKind.PATH, prefer_equals=True),
    FlagDefinition("--extrae_config_file_python", "Path to the Extrae configuration file for Python.", (ExecutionBackend.LOCAL, ExecutionBackend.SLURM), FlagValueKind.PATH, prefer_equals=True),
    FlagDefinition("--trace_label", "Label for the generated trace.", (ExecutionBackend.LOCAL, ExecutionBackend.SLURM), FlagValueKind.STRING, prefer_equals=True),
    FlagDefinition("--tracing_task_dependencies", "Enable tracing of task dependencies (true/false).", (ExecutionBackend.LOCAL, ExecutionBackend.SLURM), FlagValueKind.BOOL, prefer_equals=True),
    FlagDefinition("--generate_trace", "Enable tracing of task dependencies.", (ExecutionBackend.LOCAL, ExecutionBackend.SLURM), FlagValueKind.BOOL, prefer_equals=True),
    FlagDefinition("--delete_trace_packages", "Delete trace packages after execution (true/false).", (ExecutionBackend.LOCAL, ExecutionBackend.SLURM), FlagValueKind.BOOL, prefer_equals=True),
    FlagDefinition("--custom_threads", "Enable custom threads for the COMPSs runtime (true/false).", (ExecutionBackend.LOCAL, ExecutionBackend.SLURM), FlagValueKind.BOOL, prefer_equals=True),
    FlagDefinition("--comm", "Communication implementation class name for the COMPSs runtime.", (ExecutionBackend.LOCAL, ExecutionBackend.SLURM), FlagValueKind.STRING, prefer_equals=True),
    FlagDefinition("--conn", "Connection implementation class name for the COMPSs runtime.", (ExecutionBackend.LOCAL, ExecutionBackend.SLURM), FlagValueKind.STRING, prefer_equals=True),
    FlagDefinition("--streaming", "Enable streaming for the COMPSs runtime (type: TCP, UDP, etc.).", (ExecutionBackend.LOCAL, ExecutionBackend.SLURM), FlagValueKind.STRING, prefer_equals=True),
    FlagDefinition("--streaming_master_name", "Master name for the streaming implementation.", (ExecutionBackend.LOCAL, ExecutionBackend.SLURM), FlagValueKind.STRING, prefer_equals=True),
    FlagDefinition("--streaming_master_port", "Master port for the streaming implementation.", (ExecutionBackend.LOCAL, ExecutionBackend.SLURM), FlagValueKind.INT, prefer_equals=True),
    FlagDefinition("--scheduler", "Scheduler implementation class name for the COMPSs runtime.", (ExecutionBackend.LOCAL, ExecutionBackend.SLURM), FlagValueKind.STRING, prefer_equals=True),
    FlagDefinition("--scheduler_config_file", "Path to the scheduler configuration file.", (ExecutionBackend.LOCAL, ExecutionBackend.SLURM), FlagValueKind.PATH, prefer_equals=True),
    FlagDefinition("--checkpoint", "Checkpoint implementation class name for the COMPSs runtime.", (ExecutionBackend.LOCAL, ExecutionBackend.SLURM), FlagValueKind.STRING, prefer_equals=True),
    FlagDefinition("--checkpoint_params", "Parameters for the checkpoint implementation.", (ExecutionBackend.LOCAL, ExecutionBackend.SLURM), FlagValueKind.STRING, prefer_equals=True),
    FlagDefinition("--checkpoint_folder", "Folder for storing checkpoints.", (ExecutionBackend.LOCAL, ExecutionBackend.SLURM), FlagValueKind.PATH, prefer_equals=True),
    FlagDefinition("--library_path", "Path to the library for the COMPSs runtime.", (ExecutionBackend.LOCAL, ExecutionBackend.SLURM), FlagValueKind.PATH, prefer_equals=True),
    FlagDefinition("--classpath", "Path to the classpath for the COMPSs runtime.", (ExecutionBackend.LOCAL, ExecutionBackend.SLURM), FlagValueKind.PATH, prefer_equals=True),
    FlagDefinition("--appdir", "Path to the application directory for the COMPSs runtime.", (ExecutionBackend.LOCAL, ExecutionBackend.SLURM), FlagValueKind.PATH, prefer_equals=True),
    FlagDefinition("--env_script", "Path to the environment script for the COMPSs runtime.", (ExecutionBackend.LOCAL, ExecutionBackend.SLURM), FlagValueKind.PATH, prefer_equals=True),
    FlagDefinition("--log_dir", "Path to the log directory for the COMPSs runtime.", (ExecutionBackend.LOCAL, ExecutionBackend.SLURM), FlagValueKind.PATH, prefer_equals=True),
    FlagDefinition("--master_working_dir", "Path to the master working directory for the COMPSs runtime.", (ExecutionBackend.LOCAL, ExecutionBackend.SLURM), FlagValueKind.PATH, prefer_equals=True),
    FlagDefinition("--uuid", "UUID for the COMPSs runtime.", (ExecutionBackend.LOCAL,), FlagValueKind.INT, prefer_equals=True),
    FlagDefinition("--master_name", "Master name for the COMPSs runtime.", (ExecutionBackend.LOCAL, ExecutionBackend.SLURM), FlagValueKind.STRING, prefer_equals=True),
    FlagDefinition("--master_port", "Master port for the COMPSs runtime.", (ExecutionBackend.LOCAL, ExecutionBackend.SLURM), FlagValueKind.INT, prefer_equals=True),
    FlagDefinition("--jvm_master_opts", "JVM options for the master process of the COMPSs runtime.", (ExecutionBackend.LOCAL, ExecutionBackend.SLURM), FlagValueKind.STRING, prefer_equals=True),
    FlagDefinition("--jvm_workers_opts", "JVM options for the worker processes of the COMPSs runtime.", (ExecutionBackend.LOCAL, ExecutionBackend.SLURM), FlagValueKind.STRING, prefer_equals=True),
    FlagDefinition("--cpu_affinity", "CPU affinity for the COMPSs runtime.", (ExecutionBackend.LOCAL, ExecutionBackend.SLURM), FlagValueKind.STRING, prefer_equals=True),
    FlagDefinition("--gpu_affinity", "GPU affinity for the COMPSs runtime.", (ExecutionBackend.LOCAL, ExecutionBackend.SLURM), FlagValueKind.STRING, prefer_equals=True),
    FlagDefinition("--fpga_affinity", "FPGA affinity for the COMPSs runtime.", (ExecutionBackend.LOCAL, ExecutionBackend.SLURM), FlagValueKind.STRING, prefer_equals=True),
    FlagDefinition("--fpga_reprogram", "FPGA reprogramming command for the COMPSs runtime.", (ExecutionBackend.LOCAL, ExecutionBackend.SLURM), FlagValueKind.STRING, prefer_equals=True),
    FlagDefinition("--io_executors", "Number of I/O executors for the COMPSs runtime.", (ExecutionBackend.LOCAL, ExecutionBackend.SLURM), FlagValueKind.INT, prefer_equals=True),
    FlagDefinition("--task_count", "Number of tasks for the COMPSs runtime.", (ExecutionBackend.LOCAL, ExecutionBackend.SLURM), FlagValueKind.INT, prefer_equals=True),
    FlagDefinition("--input_profile", "Path to the input profile for the COMPSs runtime.", (ExecutionBackend.LOCAL, ExecutionBackend.SLURM), FlagValueKind.PATH, prefer_equals=True),
    FlagDefinition("--output_profile", "Path to the output profile for the COMPSs runtime.", (ExecutionBackend.LOCAL, ExecutionBackend.SLURM), FlagValueKind.PATH, prefer_equals=True),
    FlagDefinition("--PyObject_serialize", "Enable or disable PyObject serialization (true/false).", (ExecutionBackend.LOCAL, ExecutionBackend.SLURM), FlagValueKind.BOOL, prefer_equals=True),
    FlagDefinition("--persistent_worker_c", "Enable or disable persistent worker for C tasks (true/false).", (ExecutionBackend.LOCAL, ExecutionBackend.SLURM), FlagValueKind.BOOL, prefer_equals=True),
    FlagDefinition("--enable_external_adaptation", "Enable or disable external adaptation (true/false). ", (ExecutionBackend.LOCAL, ExecutionBackend.SLURM), FlagValueKind.BOOL, prefer_equals=True),
    FlagDefinition("--gen_coredump", "Enable or disable core dump generation", (ExecutionBackend.LOCAL, ExecutionBackend.SLURM), FlagValueKind.NONE),
    FlagDefinition("--keep_workingdir", "Keep the working directory after execution.", (ExecutionBackend.LOCAL, ExecutionBackend.SLURM), FlagValueKind.NONE),
    FlagDefinition("--python_interpreter", "Path to the Python interpreter for the COMPSs runtime.", (ExecutionBackend.LOCAL, ExecutionBackend.SLURM), FlagValueKind.STRING, prefer_equals=True),
    FlagDefinition("--python_propagate_virtual_environment", "Enable or disable propagation of the Python virtual environment (true/false).", (ExecutionBackend.LOCAL, ExecutionBackend.SLURM), FlagValueKind.BOOL, prefer_equals=True),
    FlagDefinition("--python_mpi_worker", "Enable or disable MPI worker for Python tasks (true/false).", (ExecutionBackend.LOCAL, ExecutionBackend.SLURM), FlagValueKind.BOOL, prefer_equals=True),
    FlagDefinition("--python_memory_profile", "Enable or disable memory profiling for Python tasks (true/false).", (ExecutionBackend.LOCAL, ExecutionBackend.SLURM), FlagValueKind.BOOL, prefer_equals=True),
    FlagDefinition("--python_cache_profiler", "Enable or disable cache profiling for Python tasks (true/false).", (ExecutionBackend.LOCAL, ExecutionBackend.SLURM), FlagValueKind.BOOL, prefer_equals=True),
    FlagDefinition("--wall_clock_limit", "Set the wall clock limit for the COMPSs runtime in seconds.", (ExecutionBackend.LOCAL, ExecutionBackend.SLURM), FlagValueKind.INT, prefer_equals=True),
    FlagDefinition("--shutdown_in_node_failure", "Enable or disable shutdown in node failure (true/false).", (ExecutionBackend.LOCAL, ExecutionBackend.SLURM), FlagValueKind.BOOL, prefer_equals=True),
    FlagDefinition("--provenance", "Generate COMPSs workflow provenance data in RO-Crate format using a YAML configuration file. Automatically activates --graph.", (ExecutionBackend.LOCAL, ExecutionBackend.SLURM), FlagValueKind.NONE, aliases=("-p")),
    FlagDefinition("--provenance_folder", "Folder to store the generated provenance data in RO-Crate format.", (ExecutionBackend.LOCAL, ExecutionBackend.SLURM), FlagValueKind.PATH, prefer_equals=True),
    FlagDefinition("--zip_provenance", "Generate a ZIP file containing the provenance data in RO-Crate format.", (ExecutionBackend.LOCAL, ExecutionBackend.SLURM), FlagValueKind.NONE, aliases=("-z")),

    # SLURM-only
    FlagDefinition("--heterogeneous", "Enable heterogeneous execution.", (ExecutionBackend.SLURM,), FlagValueKind.NONE),
    FlagDefinition("--sc_cfg", "Scheduler configuration name.", (ExecutionBackend.SLURM,), FlagValueKind.STRING, prefer_equals=True),
    FlagDefinition("--exec_time", "Execution time limit in minutes.", (ExecutionBackend.SLURM,), FlagValueKind.STRING, prefer_equals=True),
    FlagDefinition("--job_name", "SLURM job name.", (ExecutionBackend.SLURM,), FlagValueKind.STRING, prefer_equals=True),
    FlagDefinition("--queue", "Target SLURM queue.", (ExecutionBackend.SLURM,), FlagValueKind.STRING, prefer_equals=True),
    FlagDefinition("--reservation", "SLURM reservation name.", (ExecutionBackend.SLURM,), FlagValueKind.STRING, prefer_equals=True),
    FlagDefinition("--job_execution_dir", "Directory for job execution.", (ExecutionBackend.SLURM,), FlagValueKind.PATH, prefer_equals=True),
    FlagDefinition("--pre_env_script", "Path to a script to be executed before the environment script.", (ExecutionBackend.SLURM,), FlagValueKind.PATH, prefer_equals=True),
    FlagDefinition("--extra_submit_flag", "Extra flag to be passed to the SLURM submission command.", (ExecutionBackend.SLURM,), FlagValueKind.STRING, prefer_equals=True),
    FlagDefinition("--storage_container_image", "Container image for the storage implementation.", (ExecutionBackend.SLURM,), FlagValueKind.STRING, prefer_equals=True),
    FlagDefinition("--storage_cpu_affinity", "CPU affinity for the storage implementation.", (ExecutionBackend.SLURM,), FlagValueKind.STRING, prefer_equals=True),
    FlagDefinition("--constraints", "Constraints for the SLURM job.", (ExecutionBackend.SLURM,), FlagValueKind.STRING, prefer_equals=True),
    FlagDefinition("--project_name", "Project name for the SLURM job.", (ExecutionBackend.SLURM,), FlagValueKind.STRING, prefer_equals=True),
    FlagDefinition("--qos", "Quality of Service for the SLURM job.", (ExecutionBackend.SLURM,), FlagValueKind.STRING, prefer_equals=True),
    FlagDefinition("--forward_cpus_per_node", "Forward CPUs per node to the SLURM job (true/false).", (ExecutionBackend.SLURM,), FlagValueKind.BOOL, prefer_equals=True),
    FlagDefinition("--job_dependency", "Set a job dependency for the SLURM job.", (ExecutionBackend.SLURM,), FlagValueKind.STRING, prefer_equals=True),
    FlagDefinition("--forward_time_limit", "Forward time limit to the SLURM job (true/false).", (ExecutionBackend.SLURM,), FlagValueKind.BOOL, prefer_equals=True),
    FlagDefinition("--storage_home", "Storage home directory for the SLURM job.", (ExecutionBackend.SLURM,), FlagValueKind.STRING, prefer_equals=True),
    FlagDefinition("--storage_props", "Storage properties for the SLURM job.", (ExecutionBackend.SLURM,), FlagValueKind.STRING, prefer_equals=True),
    FlagDefinition("--participants", "Participants for the SLURM job.", (ExecutionBackend.SLURM,), FlagValueKind.STRING, prefer_equals=True),
    FlagDefinition("--num_nodes", "Number of nodes for the SLURM job.", (ExecutionBackend.SLURM,), FlagValueKind.INT, prefer_equals=True),
    FlagDefinition("--num_switches", "Number of switches for the SLURM job.", (ExecutionBackend.SLURM,), FlagValueKind.INT, prefer_equals=True),
    FlagDefinition("--type_cfg", "Type configuration file location for the SLURM job.", (ExecutionBackend.SLURM,), FlagValueKind.PATH, prefer_equals=True),
    FlagDefinition("--master", "Master node type for the SLURM job.", (ExecutionBackend.SLURM,), FlagValueKind.STRING, prefer_equals=True),
    FlagDefinition("--workers", "Worker node types and counts for the SLURM job.", (ExecutionBackend.SLURM,), FlagValueKind.STRING, prefer_equals=True),
    FlagDefinition("--cpus_per_node", "CPUs per node for the SLURM job.", (ExecutionBackend.SLURM,), FlagValueKind.INT, prefer_equals=True),
    FlagDefinition("--gpus_per_node", "GPUs per node for the SLURM job.", (ExecutionBackend.SLURM,), FlagValueKind.INT, prefer_equals=True),
    FlagDefinition("--fpgas_per_node", "FPGAs per node for the SLURM job.", (ExecutionBackend.SLURM,), FlagValueKind.INT, prefer_equals=True),
    FlagDefinition("--fpga_reprogram", "FPGA reprogramming command for the SLURM job.", (ExecutionBackend.SLURM,), FlagValueKind.STRING, prefer_equals=True),
    FlagDefinition("--max_tasks_per_node", "Maximum tasks per node for the SLURM job.", (ExecutionBackend.SLURM,), FlagValueKind.INT, prefer_equals=True),
    FlagDefinition("--node_memory", "Node memory in MB for the SLURM job.", (ExecutionBackend.SLURM,), FlagValueKind.STRING, prefer_equals=True),
    FlagDefinition("--node_storage_bandwidth", "Node storage bandwidth in MB for the SLURM job.", (ExecutionBackend.SLURM,), FlagValueKind.STRING, prefer_equals=True),
    FlagDefinition("--network", "Network type for the SLURM job.", (ExecutionBackend.SLURM,), FlagValueKind.STRING, prefer_equals=True),
    FlagDefinition("--prolog", "Prolog script for the SLURM job.", (ExecutionBackend.SLURM,), FlagValueKind.STRING, prefer_equals=True),
    FlagDefinition("--epilog", "Epilog script for the SLURM job.", (ExecutionBackend.SLURM,), FlagValueKind.STRING, prefer_equals=True),
    FlagDefinition("--master_working_dir", "Master working directory for the SLURM job.", (ExecutionBackend.SLURM,), FlagValueKind.PATH, prefer_equals=True),
    FlagDefinition("--worker_working_dir", "Worker working directory for the SLURM job.", (ExecutionBackend.SLURM,), FlagValueKind.PATH, prefer_equals=True),
    FlagDefinition("--worker_in_master_cpus", "Number of worker CPUs in the master node for the SLURM job.", (ExecutionBackend.SLURM,), FlagValueKind.INT, prefer_equals=True),
    FlagDefinition("--worker_in_master_memory", "Amount of worker memory in the master node for the SLURM job.", (ExecutionBackend.SLURM,), FlagValueKind.INT, prefer_equals=True),
    FlagDefinition("--worker_port_range", "Port range for workers in the SLURM job.", (ExecutionBackend.SLURM,), FlagValueKind.STRING, prefer_equals=True),
    FlagDefinition("--jvm_worker_in_master_opts", "JVM options for workers in master for the SLURM job.", (ExecutionBackend.SLURM,), FlagValueKind.STRING, prefer_equals=True),
    FlagDefinition("--container_image", "Container image for the SLURM job.", (ExecutionBackend.SLURM,), FlagValueKind.PATH, prefer_equals=True),
    FlagDefinition("--container_compss_path", "Path to COMPSs installation inside the container for the SLURM job.", (ExecutionBackend.SLURM,), FlagValueKind.PATH, prefer_equals=True),
    FlagDefinition("--container_opts", "Extra options for the container execution in the SLURM job.", (ExecutionBackend.SLURM,), FlagValueKind.STRING, prefer_equals=True),
    FlagDefinition("--elasticity", "Maximum extra nodes for elasticity in the SLURM job.", (ExecutionBackend.SLURM,), FlagValueKind.STRING, prefer_equals=True),
    FlagDefinition("--automatic_scaling", "Enable or disable automatic scaling for the SLURM job (true/false).", (ExecutionBackend.SLURM,), FlagValueKind.BOOL, prefer_equals=True),
    FlagDefinition("--jupyter_notebook", "Path to a Jupyter notebook to be executed in the SLURM job.", (ExecutionBackend.SLURM,), FlagValueKind.PATH, prefer_equals=True),
    FlagDefinition("--ipython", "Enable execution of an IPython shell for the SLURM job.", (ExecutionBackend.SLURM,), FlagValueKind.NONE),
    FlagDefinition("--ear", "Enable or disable execution after recovery (true/false or path to recovery file).", (ExecutionBackend.SLURM,), FlagValueKind.STRING, prefer_equals=True),
)

# DO NOT DELETE THIS FUNCTION
def build_flag_options(backend: ExecutionBackend) -> list[tuple[str, str]]:
    choices: list[tuple[str, str]] = []

    for flag in FLAG_DEFINITIONS:
        if backend not in flag.backend_scope:
            continue

        display = flag.name if flag.value_kind == FlagValueKind.NONE else f"{flag.name}=<value>"
        choices.append((display, flag.description))

    return choices

PROVENANCE_FLAGS = {"--provenance", "-p"}
VALUE_FLAG_BASES = {flag.name for flag in FLAG_DEFINITIONS if flag.value_kind != FlagValueKind.NONE}

FLAG_CANONICAL_MAP = {
"-p": "--provenance",
"-d": "--debug",
"-z": "--zip_provenance",
}

LOCAL_FLAG_OPTIONS = build_flag_options(ExecutionBackend.LOCAL)
SLURM_FLAG_OPTIONS = build_flag_options(ExecutionBackend.SLURM)

def _canonical_flag_base(flag: str) -> str:
    raw = (flag or "").split("=", 1)[0].split(" - ", 1)[0].strip()
    return FLAG_CANONICAL_MAP.get(raw, raw)

def _option_takes_value(flag_spec: str) -> bool:
    return "=" in flag_spec

LOCAL_FLAG_BASES = {_canonical_flag_base(flag) for flag, _ in LOCAL_FLAG_OPTIONS}
SLURM_FLAG_BASES = {_canonical_flag_base(flag) for flag, _ in SLURM_FLAG_OPTIONS}
SLURM_ONLY_FLAG_BASES = SLURM_FLAG_BASES - LOCAL_FLAG_BASES
VALUE_FLAG_BASES = {_canonical_flag_base(flag) for flag, _ in (LOCAL_FLAG_OPTIONS + SLURM_FLAG_OPTIONS) if _option_takes_value(flag)}


# DO NOT DELETE THIS FUNCTION
def _flag_base(flag: str) -> str:
    return _canonical_flag_base(flag)

# DO NOT DELETE THIS FUNCTION
def _resolve_flag_definition(flag_name: str):
    base = _canonical_flag_base(flag_name)
    for flag in FLAG_DEFINITIONS:
        if base == flag.name or base in flag.aliases:
            return flag
    return None

# DO NOT DELETE THIS FUNCTION
def _flag_requires_value(flag_name: str) -> bool:
    definition = _resolve_flag_definition(flag_name)
    if definition is None:
        return False
    return definition.value_kind != FlagValueKind.NONE

# DO NOT DELETE THIS FUNCTION
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

# DO NOT DELETE THIS FUNCTION
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
        elif (_flag_base(token) in VALUE_FLAG_BASES and index + 1 < len(current_command) and not current_command[index + 1].startswith("-")):
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