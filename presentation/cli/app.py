"""COMPSs Reproducibility Service - Rich CLI entrypoint.

This module only orchestrates: it wires the infrastructure adapters into
the application use cases, drives them in order, and hands results to
`view.py` for rendering. No business logic lives here.
"""

from __future__ import annotations

import argparse
import uuid
import logging
from pathlib import Path

from rich.prompt import Prompt
from datetime import datetime



from application.use_cases.build_execution_plan import (
    BuildExecutionPlanFailure,
    BuildExecutionPlanRequest,
    DefaultBuildExecutionPlanService,
)
from application.use_cases.configure_new_dataset import (
    ConfigureNewDatasetRequest,
    DefaultConfigureNewDatasetService,
)
from application.use_cases.import_crate import (
    DefaultImportCrateService,
    ImportCrateRequest,
)
from application.use_cases.inspect_crate import (
    DefaultInspectCrateService,
    InspectCrateRequest,
)
from application.use_cases.prepare_provenance import (
    DefaultPrepareProvenanceService,
    PrepareProvenanceRequest,
)
from application.use_cases.verify_inputs import (
    DefaultVerifyInputsService,
    VerifyInputsRequest,
    VerifyInputsStatus,
)
from config.settings import AppSettings, build_default_settings
from domain.errors import ServiceError
from domain.models.execution import ExecutionBackend
from infrastructure.adapters import (
    CrateMetadataNormalizer,
    CrateMetadataParser,
    LocalCrateSourceAcquirer,
    LocalCrateSourceResolver,
    LocalCrateSourceValidator,
    LocalFileSystem,
    ShutilExecutionBackendDetector,
    SubprocessExecutionSubmitter,
)
from presentation.cli import view


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="reproducibility_service",
        description="Reproduce a COMPSs workflow run from an RO-Crate.",
    )
    parser.add_argument("source", help="Local directory, .zip file, or URL of the RO-Crate")
    parser.add_argument("--run-id", help="Identifier for this run (default: random)")
    parser.add_argument(
        "--backend", choices=["auto", "local", "slurm"], default="auto", help="Execution backend"
    )
    parser.add_argument("--command", help="Override the COMPSs submission command line")
    parser.add_argument(
        "--extra-flag", action="append", default=[], help="Extra runtime flag (repeatable)"
    )
    parser.add_argument("--provenance", action="store_true", help="Enable provenance and write ro-crate-info.yaml")
    parser.add_argument("--submitter-name", default="Unknown Submitter")
    parser.add_argument("--submitter-email")
    parser.add_argument("--submitter-org")
    parser.add_argument("--submitter-orcid")
    parser.add_argument("--submitter-ror")
    parser.add_argument("--new-dataset", help="Optional dataset directory to copy into the crate before running")
    parser.add_argument("-y", "--yes", action="store_true", help="Skip confirmation prompts")
    return parser


def run_app(argv: list[str] | None = None) -> int:
    args = build_arg_parser().parse_args(argv)
    settings = build_default_settings()
    # run_id = args.run_id or uuid.uuid4().hex[:8] # Random 8-character hex string.
    run_id = args.run_id or datetime.now().strftime("%Y%m%d_%H%M%S")
    source_path = Path(args.source).expanduser()
    runs_root = source_path.resolve().parent
    run_directory = runs_root / f"reproducibility_service_{run_id}"

    logger = _build_run_logger(run_directory)
    logger.info("source=%s", args.source)

    view.print_banner()

    try:
        crate, plan_result = _run_pipeline(args, settings, run_directory, logger)
    except ServiceError as exc:
        logger.exception("service_error=%s details=%s", exc.message, exc.details)
        view.print_error(exc.message, exc.details)
        return 1
    except KeyboardInterrupt:
        logger.info("final_status=aborted_by_user")
        view.console.print("\n[yellow]Aborted by user.[/yellow]")
        return 130

    if plan_result is None:
        logger.info("final_status=not_executed")
        return 0

    logger.info(
        "backend=%s provenance_enabled=%s command=%s",
        plan_result.plan.backend.value,
        plan_result.plan.provenance_enabled,
        plan_result.plan.command.as_string(),
    )

    view.console.print(f"Running submission command: {plan_result.plan.command.as_string()}")

    submitter = SubprocessExecutionSubmitter()
    outcome = view.run_with_spinner("Executing workflow...", submitter.submit, plan_result.submission)
    view.print_final_summary(outcome)

    logger.info(
        "final_status=%s return_code=%s",
        "succeeded" if outcome.succeeded else "failed",
        outcome.result.return_code,
    )
    return 0 if outcome.succeeded else 1


def _run_pipeline(args: argparse.Namespace, settings: AppSettings, run_directory: Path, logger: logging.Logger):
    file_system = LocalFileSystem()

    import_service = DefaultImportCrateService(
        resolver=LocalCrateSourceResolver(),
        validator=LocalCrateSourceValidator(),
        acquirer=LocalCrateSourceAcquirer(),
        file_system=file_system,
        workflow_dir_name=settings.workflow_dir_name,
        log_dir_name=settings.log_dir_name,
        results_dir_name=settings.results_dir_name,
    )
    inspect_service = DefaultInspectCrateService(
        parser=CrateMetadataParser(), normalizer=CrateMetadataNormalizer()
    )
    dataset_service = DefaultConfigureNewDatasetService(file_system=file_system)
    verify_service = DefaultVerifyInputsService(file_system=file_system)
    plan_service = DefaultBuildExecutionPlanService(
        backend_detector=ShutilExecutionBackendDetector(),
        log_dir_name=settings.log_dir_name,
        results_dir_name=settings.results_dir_name,
    )
    provenance_service = DefaultPrepareProvenanceService(file_system=file_system)

    import_result = view.run_with_spinner(
        "Importing crate source...",
        import_service.execute,
        ImportCrateRequest(raw_source=args.source, run_directory=run_directory),
    )
    view.print_import_result(import_result)

    inspect_result = view.run_with_spinner(
        "Inspecting crate metadata...",
        inspect_service.execute,
        InspectCrateRequest(crate_root=import_result.location.working_path),
    )
    view.print_inspect_result(inspect_result, inspect_result.crate)

    if inspect_result.crate is None:
        logger.info("final_status=invalid_crate_metadata")
        view.print_error("Could not build a usable crate summary from the metadata found.")
        return None, None

    crate = inspect_result.crate

    if args.new_dataset:
        dataset_result = dataset_service.execute(
            ConfigureNewDatasetRequest(crate=crate, source_dataset_root=Path(args.new_dataset))
        )
        view.console.print(
            f"  Dataset staged: {len(dataset_result.copied_items)} item(s) copied into the crate\n"
        )

    verify_result = verify_service.execute(VerifyInputsRequest(crate=crate))
    view.print_verification_table(verify_result)

    if verify_result.status == VerifyInputsStatus.FAILED:
        if not args.yes and not view.console.input(
            "[yellow]Some inputs are missing. Continue anyway ? [y/N]: [/yellow]"
        ).lower().startswith("y"):
            logger.info("final_status=aborted_after_failed_verification")
            view.console.print("Aborted after failed verification.")
            return crate, None

    provenance_flag = args.provenance
    if not args.yes and not provenance_flag:
        provenance_flag = view.console.input(
            "[yellow]Do you want to enable provenance for this reproduction ? [y/N]: [/yellow]"
        ).lower().startswith("y")

    plan_result = _build_plan(args, plan_service, crate, run_directory, provenance_flag)
    logger.info(
        "resolved_command=%s backend=%s provenance_enabled=%s",
        plan_result.plan.command.as_string(),
        plan_result.plan.backend.value,
        provenance_flag,
    )
    view.console.print()
    view.console.print(f"Current submission command: {plan_result.plan.command.as_string()}")

    if not args.yes and view.console.input( "[yellow]Do you want to modify the submission command ? [y/N]: [/yellow]" ).lower().startswith("y"):
        plan_result = _update_plan_with_selected_flags( args=args, plan_service=plan_service, crate=crate, run_directory=run_directory, provenance_enabled=provenance_flag, current_plan=plan_result, logger=logger)

    view.print_execution_plan(plan_result.plan)

    if provenance_flag:
        provenance_result = provenance_service.execute(
            PrepareProvenanceRequest(
                crate=crate,
                provenance_root=run_directory,
                submitter_name=args.submitter_name,
                submitter_email=args.submitter_email,
                submitter_organization=args.submitter_org,
                submitter_orcid=args.submitter_orcid,
                submitter_ror=args.submitter_ror,
            )
        )
        if provenance_result.created_metadata_file:
            logger.info("provenance_metadata=%s", provenance_result.created_metadata_file)
        view.print_provenance_result(provenance_result)

    return crate, plan_result


def _build_plan(args: argparse.Namespace, plan_service, crate, run_directory: Path, provenance_enabled: bool):
    backend = ExecutionBackend(args.backend)
    try:
        return plan_service.execute(
            BuildExecutionPlanRequest(
                crate=crate,
                run_directory=run_directory,
                backend=backend,
                provenance_enabled=provenance_enabled,
                extra_flags=tuple(args.extra_flag),
                submission_command=args.command,
            )
        )
    except BuildExecutionPlanFailure:
        if args.yes or args.command:
            raise
        manual_command = Prompt.ask(
            "[yellow]Could not find a submission command in the crate. Enter one manually (e.g. 'runcompss main.py')[/yellow]"
        )
        return plan_service.execute(
            BuildExecutionPlanRequest(
                crate=crate,
                run_directory=run_directory,
                backend=backend,
                provenance_enabled=provenance_enabled,
                extra_flags=tuple(args.extra_flag),
                submission_command=manual_command,
            )
        )

def _build_run_logger(run_directory: Path) -> logging.Logger:
    log_dir = run_directory / "log"
    log_dir.mkdir(parents=True, exist_ok=True)

    logger = logging.getLogger(f"reproducibility_service.{run_directory.name}")
    logger.setLevel(logging.INFO)
    logger.propagate = False

    if not any(isinstance(handler, logging.FileHandler) for handler in logger.handlers):
        file_handler = logging.FileHandler(log_dir / "rs_log.txt", encoding="utf-8")
        file_handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
        logger.addHandler(file_handler)

    return logger


def _update_plan_with_selected_flags(
    args: argparse.Namespace,
    plan_service,
    crate,
    run_directory: Path,
    provenance_enabled: bool,
    current_plan,
    logger: logging.Logger,
):
    selected_flags = view.select_submission_flags(
        current_plan.plan.backend,
        current_plan.plan.command.as_list(),
    )
    if selected_flags is None:
        return current_plan

    args.command = _replace_submission_flags(
        current_plan.plan.command.as_list(),
        current_plan.plan.backend,
        selected_flags,
    )
    args.extra_flag = []

    plan_result = _build_plan(args, plan_service, crate, run_directory, provenance_enabled)
    logger.info(
        "resolved_command=%s backend=%s provenance_enabled=%s",
        plan_result.plan.command.as_string(),
        plan_result.plan.backend.value,
        provenance_enabled,
    )
    return plan_result


def _replace_submission_flags(
    command_parts: list[str],
    backend: ExecutionBackend,
    selected_flags: list[str],
) -> str:
    if not command_parts:
        return " ".join(selected_flags)

    option_set = view.LOCAL_FLAG_OPTIONS if backend == ExecutionBackend.LOCAL else view.SLURM_FLAG_OPTIONS
    toggleable_bases = {_flag_base(flag) for flag, _description in option_set}

    filtered_arguments = _strip_toggleable_flags(command_parts[1:], toggleable_bases)
    updated_parts = [command_parts[0], *selected_flags, *filtered_arguments]
    return " ".join(updated_parts)


def _strip_toggleable_flags(arguments: list[str], toggleable_bases: set[str]) -> list[str]:
    filtered: list[str] = []
    index = 0

    while index < len(arguments):
        token = arguments[index]
        base = _flag_base(token)

        if base in toggleable_bases:
            index += 1
            if token == base and index < len(arguments) and not arguments[index].startswith("-"):
                index += 1
            continue

        filtered.append(token)
        index += 1

    return filtered


def _flag_base(flag: str) -> str:
    return flag.split("=", 1)[0]


def main() -> None:
    raise SystemExit(run_app())


if __name__ == "__main__":
    main()