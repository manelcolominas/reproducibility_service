from __future__ import annotations

from dataclasses import dataclass, field, replace
from pathlib import Path
from types import MappingProxyType
from typing import Mapping, Sequence


ENV_PREFIX = "COMPSS_RS_"

DEFAULT_APP_NAME = "COMPSs Reproducibility Service"
DEFAULT_APP_VERSION = "2.0.0"

DEFAULT_SERVICE_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_RUNS_ROOT = DEFAULT_SERVICE_ROOT / "runs"
DEFAULT_TEMPLATES_ROOT = DEFAULT_SERVICE_ROOT / "APP-REQ"


class SettingsError(ValueError):
    """Raised when configuration values are invalid."""


def _parse_bool(value: str | bool | None, default: bool) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value

    normalized = value.strip().lower()
    if normalized in {"1", "true", "yes", "y", "on"}:
        return True
    if normalized in {"0", "false", "no", "n", "off"}:
        return False
    raise SettingsError(f"Invalid boolean value: {value!r}")


def _parse_int(value: str | int | None, default: int, minimum: int = 1) -> int:
    if value is None:
        result = default
    elif isinstance(value, int):
        result = value
    else:
        try:
            result = int(value.strip())
        except ValueError as exc:
            raise SettingsError(f"Invalid integer value: {value!r}") from exc

    if result < minimum:
        raise SettingsError(f"Integer value must be >= {minimum}: {result}")
    return result


def _parse_float(value: str | float | None, default: float, minimum: float = 0.0) -> float:
    if value is None:
        result = default
    elif isinstance(value, float):
        result = value
    else:
        try:
            result = float(value.strip())
        except ValueError as exc:
            raise SettingsError(f"Invalid float value: {value!r}") from exc

    if result < minimum:
        raise SettingsError(f"Float value must be >= {minimum}: {result}")
    return result


def _parse_csv(value: str | Sequence[str] | None) -> tuple[str, ...]:
    if value is None:
        return ()
    if isinstance(value, str):
        items = [item.strip() for item in value.split(",")]
        return tuple(item for item in items if item)
    return tuple(item.strip() for item in value if item.strip())


def _default_metadata_aliases() -> Mapping[str, tuple[str, ...]]:
    return MappingProxyType(
        {
            "name": ("name", "title", "workflowName"),
            "description": ("description", "summary", "abstract"),
            "authors": ("authors", "author", "creator"),
            "submitter": ("Submitter", "Agent", "submitter", "creator"),
            "instrument": ("instrument", "mainEntity", "main_file", "mainFile"),
            "object": ("object", "input", "inputs", "source"),
            "result": ("result", "output", "outputs", "artifact"),
            "compss_version": ("version", "compssVersion", "compss_version"),
            "data_persistence": ("data_persistence", "dataPersistence", "data-persistence"),
        }
    )


@dataclass(frozen=True, slots=True)
class RuntimeSettings:
    app_name: str = DEFAULT_APP_NAME
    app_version: str = DEFAULT_APP_VERSION
    debug: bool = False
    interactive: bool = True
    log_level: str = "INFO"

    def validate(self) -> None:
        if not self.app_name.strip():
            raise SettingsError("app_name cannot be empty")
        if not self.app_version.strip():
            raise SettingsError("app_version cannot be empty")
        if not self.log_level.strip():
            raise SettingsError("log_level cannot be empty")


@dataclass(frozen=True, slots=True)
class PathsSettings:
    service_root: Path = DEFAULT_SERVICE_ROOT
    runs_root: Path = DEFAULT_RUNS_ROOT
    templates_root: Path = DEFAULT_TEMPLATES_ROOT
    workflow_dir_name: str = "Workflow"
    log_dir_name: str = "log"
    results_dir_name: str = "Results"
    dataset_dir_name: str = "dataset"
    new_dataset_dir_name: str = "new_dataset"
    remote_dataset_dir_name: str = "remote_dataset"
    application_sources_dir_name: str = "application_sources"
    metadata_filename: str = "ro-crate-metadata.json"
    crate_info_filename: str = "ro-crate-info.yaml"
    command_filename: str = "compss_submission_command_line.txt"

    def validate(self) -> None:
        for path_name, path_value in {
            "service_root": self.service_root,
            "runs_root": self.runs_root,
            "templates_root": self.templates_root,
        }.items():
            if not isinstance(path_value, Path):
                raise SettingsError(f"{path_name} must be a pathlib.Path instance")

        for field_name in (
            "workflow_dir_name",
            "log_dir_name",
            "results_dir_name",
            "dataset_dir_name",
            "new_dataset_dir_name",
            "remote_dataset_dir_name",
            "application_sources_dir_name",
            "metadata_filename",
            "crate_info_filename",
            "command_filename",
        ):
            if not getattr(self, field_name).strip():
                raise SettingsError(f"{field_name} cannot be empty")

    def run_directory(self, run_id: str) -> Path:
        if not run_id.strip():
            raise SettingsError("run_id cannot be empty")
        return self.runs_root / f"reproducibility_service_{run_id}"

    def workflow_directory(self, run_directory: Path) -> Path:
        return run_directory / self.workflow_dir_name

    def log_directory(self, run_directory: Path) -> Path:
        return run_directory / self.log_dir_name

    def results_directory(self, run_directory: Path) -> Path:
        return run_directory / self.results_dir_name

    def workflow_metadata_path(self, workflow_root: Path) -> Path:
        return workflow_root / self.metadata_filename

    def crate_info_path(self, workflow_root: Path) -> Path:
        return workflow_root / self.crate_info_filename


@dataclass(frozen=True, slots=True)
class UISettings:
    table_page_size: int = 20
    tree_max_depth: int = 6
    confirm_by_default: bool = False
    show_progress: bool = True
    color_system: str = "auto"

    def validate(self) -> None:
        if self.table_page_size < 1:
            raise SettingsError("table_page_size must be >= 1")
        if self.tree_max_depth < 1:
            raise SettingsError("tree_max_depth must be >= 1")
        if not self.color_system.strip():
            raise SettingsError("color_system cannot be empty")


@dataclass(frozen=True, slots=True)
class NetworkSettings:
    timeout_seconds: float = 30.0
    retries: int = 3
    retry_backoff_seconds: float = 1.0
    verify_tls: bool = True
    user_agent: str = "COMPSS-Reproducibility-Service/2.0"

    def validate(self) -> None:
        if self.timeout_seconds <= 0:
            raise SettingsError("timeout_seconds must be > 0")
        if self.retries < 0:
            raise SettingsError("retries must be >= 0")
        if self.retry_backoff_seconds < 0:
            raise SettingsError("retry_backoff_seconds must be >= 0")
        if not self.user_agent.strip():
            raise SettingsError("user_agent cannot be empty")


@dataclass(frozen=True, slots=True)
class ExecutionSettings:
    preferred_backend: str = "auto"
    local_runner: str = "runcompss"
    slurm_runner: str = "enqueue_compss"
    capture_output: bool = True
    allow_shell: bool = False
    cleanup_on_failure: bool = False
    default_runtime_flags: tuple[str, ...] = ()

    def validate(self) -> None:
        if not self.preferred_backend.strip():
            raise SettingsError("preferred_backend cannot be empty")
        if not self.local_runner.strip():
            raise SettingsError("local_runner cannot be empty")
        if not self.slurm_runner.strip():
            raise SettingsError("slurm_runner cannot be empty")
        if not all(flag.strip() for flag in self.default_runtime_flags):
            raise SettingsError("default_runtime_flags cannot contain empty strings")


@dataclass(frozen=True, slots=True)
class VerificationSettings:
    verify_content_size: bool = True
    verify_modified_time: bool = True
    verify_remote_datasets: bool = True
    verify_accessibility_for_dpf: bool = True
    fail_fast: bool = False

    def validate(self) -> None:
        return None


@dataclass(frozen=True, slots=True)
class MetadataSettings:
    field_aliases: Mapping[str, tuple[str, ...]] = field(default_factory=_default_metadata_aliases)
    fallback_search_order: tuple[str, ...] = (
        "ro-crate-info.yaml",
        "ro-crate-info.yml",
        "metadata.yaml",
        "metadata.yml",
    )

    def validate(self) -> None:
        if not self.field_aliases:
            raise SettingsError("field_aliases cannot be empty")
        for canonical_name, aliases in self.field_aliases.items():
            if not canonical_name.strip():
                raise SettingsError("field_aliases contains an empty canonical field name")
            if not aliases:
                raise SettingsError(f"field_aliases[{canonical_name!r}] cannot be empty")
            if not all(alias.strip() for alias in aliases):
                raise SettingsError(f"field_aliases[{canonical_name!r}] contains an empty alias")
        if not self.fallback_search_order:
            raise SettingsError("fallback_search_order cannot be empty")

    def aliases_for(self, canonical_name: str) -> tuple[str, ...]:
        return self.field_aliases.get(canonical_name, (canonical_name,))


@dataclass(frozen=True, slots=True)
class AppSettings:
    runtime: RuntimeSettings = field(default_factory=RuntimeSettings)
    paths: PathsSettings = field(default_factory=PathsSettings)
    ui: UISettings = field(default_factory=UISettings)
    network: NetworkSettings = field(default_factory=NetworkSettings)
    execution: ExecutionSettings = field(default_factory=ExecutionSettings)
    verification: VerificationSettings = field(default_factory=VerificationSettings)
    metadata: MetadataSettings = field(default_factory=MetadataSettings)

    def validate(self) -> None:
        self.runtime.validate()
        self.paths.validate()
        self.ui.validate()
        self.network.validate()
        self.execution.validate()
        self.verification.validate()
        self.metadata.validate()

    def with_runtime(self, **changes) -> AppSettings:
        return replace(self, runtime=replace(self.runtime, **changes))

    def with_paths(self, **changes) -> AppSettings:
        return replace(self, paths=replace(self.paths, **changes))

    def with_ui(self, **changes) -> AppSettings:
        return replace(self, ui=replace(self.ui, **changes))

    def with_network(self, **changes) -> AppSettings:
        return replace(self, network=replace(self.network, **changes))

    def with_execution(self, **changes) -> AppSettings:
        return replace(self, execution=replace(self.execution, **changes))

    def with_verification(self, **changes) -> AppSettings:
        return replace(self, verification=replace(self.verification, **changes))

    def with_metadata(self, **changes) -> AppSettings:
        return replace(self, metadata=replace(self.metadata, **changes))


def _env_name(key: str) -> str:
    return f"{ENV_PREFIX}{key}"


def _get_env(env: Mapping[str, str], key: str) -> str | None:
    value = env.get(_env_name(key))
    if value is None:
        return None
    stripped = value.strip()
    return stripped if stripped else None


def build_default_settings(service_root: Path | None = None) -> AppSettings:
    root = service_root or DEFAULT_SERVICE_ROOT
    paths = PathsSettings(
        service_root=root,
        runs_root=root / "runs",
        templates_root=root / "APP-REQ",
    )
    settings = AppSettings(paths=paths)
    settings.validate()
    return settings


def load_settings(
    env: Mapping[str, str] | None = None,
    service_root: Path | None = None,
) -> AppSettings:
    environment = env or {}

    settings = build_default_settings(service_root)

    runtime = settings.runtime
    paths = settings.paths
    ui = settings.ui
    network = settings.network
    execution = settings.execution
    verification = settings.verification
    metadata = settings.metadata

    runtime = replace(
        runtime,
        app_name=_get_env(environment, "APP_NAME") or runtime.app_name,
        app_version=_get_env(environment, "APP_VERSION") or runtime.app_version,
        debug=_parse_bool(_get_env(environment, "DEBUG"), runtime.debug),
        interactive=_parse_bool(_get_env(environment, "INTERACTIVE"), runtime.interactive),
        log_level=_get_env(environment, "LOG_LEVEL") or runtime.log_level,
    )

    paths = replace(
        paths,
        service_root=Path(_get_env(environment, "SERVICE_ROOT") or str(paths.service_root)),
        runs_root=Path(_get_env(environment, "RUNS_ROOT") or str(paths.runs_root)),
        templates_root=Path(_get_env(environment, "TEMPLATES_ROOT") or str(paths.templates_root)),
        workflow_dir_name=_get_env(environment, "WORKFLOW_DIR_NAME") or paths.workflow_dir_name,
        log_dir_name=_get_env(environment, "LOG_DIR_NAME") or paths.log_dir_name,
        results_dir_name=_get_env(environment, "RESULTS_DIR_NAME") or paths.results_dir_name,
        dataset_dir_name=_get_env(environment, "DATASET_DIR_NAME") or paths.dataset_dir_name,
        new_dataset_dir_name=_get_env(environment, "NEW_DATASET_DIR_NAME") or paths.new_dataset_dir_name,
        remote_dataset_dir_name=_get_env(environment, "REMOTE_DATASET_DIR_NAME") or paths.remote_dataset_dir_name,
        application_sources_dir_name=_get_env(environment, "APPLICATION_SOURCES_DIR_NAME") or paths.application_sources_dir_name,
        metadata_filename=_get_env(environment, "METADATA_FILENAME") or paths.metadata_filename,
        crate_info_filename=_get_env(environment, "CRATE_INFO_FILENAME") or paths.crate_info_filename,
        command_filename=_get_env(environment, "COMMAND_FILENAME") or paths.command_filename,
    )

    ui = replace(
        ui,
        table_page_size=_parse_int(_get_env(environment, "TABLE_PAGE_SIZE"), ui.table_page_size),
        tree_max_depth=_parse_int(_get_env(environment, "TREE_MAX_DEPTH"), ui.tree_max_depth),
        confirm_by_default=_parse_bool(_get_env(environment, "CONFIRM_BY_DEFAULT"), ui.confirm_by_default),
        show_progress=_parse_bool(_get_env(environment, "SHOW_PROGRESS"), ui.show_progress),
        color_system=_get_env(environment, "COLOR_SYSTEM") or ui.color_system,
    )

    network = replace(
        network,
        timeout_seconds=_parse_float(_get_env(environment, "TIMEOUT_SECONDS"), network.timeout_seconds, minimum=0.001),
        retries=_parse_int(_get_env(environment, "RETRIES"), network.retries, minimum=0),
        retry_backoff_seconds=_parse_float(
            _get_env(environment, "RETRY_BACKOFF_SECONDS"),
            network.retry_backoff_seconds,
            minimum=0.0,
        ),
        verify_tls=_parse_bool(_get_env(environment, "VERIFY_TLS"), network.verify_tls),
        user_agent=_get_env(environment, "USER_AGENT") or network.user_agent,
    )

    execution = replace(
        execution,
        preferred_backend=_get_env(environment, "PREFERRED_BACKEND") or execution.preferred_backend,
        local_runner=_get_env(environment, "LOCAL_RUNNER") or execution.local_runner,
        slurm_runner=_get_env(environment, "SLURM_RUNNER") or execution.slurm_runner,
        capture_output=_parse_bool(_get_env(environment, "CAPTURE_OUTPUT"), execution.capture_output),
        allow_shell=_parse_bool(_get_env(environment, "ALLOW_SHELL"), execution.allow_shell),
        cleanup_on_failure=_parse_bool(_get_env(environment, "CLEANUP_ON_FAILURE"), execution.cleanup_on_failure),
        default_runtime_flags=_parse_csv(_get_env(environment, "DEFAULT_RUNTIME_FLAGS")) or execution.default_runtime_flags,
    )

    verification = replace(
        verification,
        verify_content_size=_parse_bool(_get_env(environment, "VERIFY_CONTENT_SIZE"), verification.verify_content_size),
        verify_modified_time=_parse_bool(_get_env(environment, "VERIFY_MODIFIED_TIME"), verification.verify_modified_time),
        verify_remote_datasets=_parse_bool(_get_env(environment, "VERIFY_REMOTE_DATASETS"), verification.verify_remote_datasets),
        verify_accessibility_for_dpf=_parse_bool(
            _get_env(environment, "VERIFY_ACCESSIBILITY_FOR_DPF"),
            verification.verify_accessibility_for_dpf,
        ),
        fail_fast=_parse_bool(_get_env(environment, "FAIL_FAST"), verification.fail_fast),
    )

    metadata = replace(metadata)

    loaded = AppSettings(
        runtime=runtime,
        paths=paths,
        ui=ui,
        network=network,
        execution=execution,
        verification=verification,
        metadata=metadata,
    )
    loaded.validate()
    return loaded


def default_settings() -> AppSettings:
    return build_default_settings()


__all__ = [
    "AppSettings",
    "DEFAULT_APP_NAME",
    "DEFAULT_APP_VERSION",
    "DEFAULT_RUNS_ROOT",
    "DEFAULT_SERVICE_ROOT",
    "DEFAULT_TEMPLATES_ROOT",
    "ExecutionSettings",
    "MetadataSettings",
    "NetworkSettings",
    "PathsSettings",
    "RuntimeSettings",
    "SettingsError",
    "UISettings",
    "VerificationSettings",
    "build_default_settings",
    "default_settings",
    "load_settings",
]