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
    SubmissionCommandEditKind,
    SubmissionCommandEdit,
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
from config import settings
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
    LocalPyCompssMetadataInspector,
    ShutilExecutionBackendDetector,
    SubprocessExecutionParticipant,
)
from presentation.cli import view


def build_arg_parser() -> argparse.ArgumentParser:
    # create an argument parser for the CLI, with a description of the program and its usage, for example the source, run-id, backend, command, provenance.
    # The parser will be used to parse the command line arguments passed to the program.
    # the library ArgumentParser is used to create command line interfaces. It automatically generates help and usage messages and issues errors when users give the program invalid arguments.
    parser = argparse.ArgumentParser(
        prog="reproducibility_service",
        description="Reproduce a COMPSs workflow run from an RO-Crate.",
    )
    # the source is a positional argument, can be a local directory, a .zip file, or a URL
    # the source is a positional argument, it is mandatory and does not require a flag, doesn't begin with a dash (- or --). The user must provide it when running the command.
    parser.add_argument("source", help="Local directory, .zip file, or URL of the RO-Crate")

    # I can't ensure this flags work properly, so I will comment them out for now. They are not essential for the basic functionality.
    
    # parser.add_argument("--run-id", help="Identifier for this run (default: random)")
    # parser.add_argument("--backend", choices=["auto", "local", "slurm"], default="auto", help="Execution backend"
    # )
    # parser.add_argument("--command", help="Override the COMPSs submission command line")
    # parser.add_argument("--extra-flag", action="append", default=[], help="Extra runtime flag (repeatable)")
    # parser.add_argument("--provenance", "-p", action="store_true", help="Enable provenance and write ro-crate-info.yaml")
    # parser.add_argument("--participant-name", default=None)
    # parser.add_argument("--participant-email")
    # parser.add_argument("--participant-org")
    # parser.add_argument("--participant-orcid")
    # parser.add_argument("--participant-ror")
    # parser.add_argument("-y", "--yes", action="store_true", help="Skip confirmation prompts")
    return parser

def run_app(argv: list[str] | None = None) -> int:
    # parse_args(argv) returns a Namespace object containing the parsed command line arguments.
    # for example, if the user runs the command `reproducibility_service my_crate.zip --backend slurm`,
    # the Namespace object will contain the attributes `source` with value `my_crate.zip` and `backend` with value `slurm`.
    # Namespace(source='input.txt', backend='slurm')

    # so build_arg_parser().parse_args(argv) returns a Namespace object containing the parsed command line arguments.
    args = build_arg_parser().parse_args(argv)
    settings = build_default_settings()
    run_id = args.run_id or datetime.now().strftime("%Y%m%d_%H%M%S")

    source_arg = args.source.strip()
    source_is_url = source_arg.startswith(("http://", "https://"))

    if source_is_url:
        runs_root = Path.cwd()
        shared_crate_directory = runs_root / settings.copied_downloaded_crate_dir_name

    else:
        source_path = Path(source_arg).expanduser().resolve()
        runs_root = source_path.parent

        if source_path.suffix.lower() == ".zip":
            # Extract into a folder next to the archive, not into the archive file itself
            shared_crate_directory = source_path.with_suffix("")
        else:
            shared_crate_directory = source_path

    workspace_directory = runs_root / f"reproducibility_service_{run_id}"


    logger = _build_run_logger(workspace_directory)
    logger.info("source=%s", args.source)

    view.print_banner()

    try:
        crate, plan_result = _run_pipeline(args, settings, workspace_directory, shared_crate_directory, logger)
    except ServiceError as exc:
        logger.exception("service_error=%s details=%s", exc.message, exc.details)
        view.print_error(exc.message, exc.details)
        return 1
    except KeyboardInterrupt:
        logger.info("final_status=aborted_by_user")
        view.console.print("\n[yellow]User aborted reproducibility service.[/yellow]")
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

    participant = SubprocessExecutionParticipant()
    outcome = view.run_with_spinner("Executing workflow...", participant.submit, plan_result.submission)
    view.print_final_summary(outcome)

    logger.info(
        "final_status=%s return_code=%s",
        "succeeded" if outcome.succeeded else "failed",
        outcome.result.return_code,
    )
    return 0 if outcome.succeeded else 1


def _run_pipeline( args: argparse.Namespace, settings: AppSettings, workspace_directory: Path, shared_crate_directory: Path, logger: logging.Logger ):

    file_system = LocalFileSystem()

    import_service = DefaultImportCrateService(
        resolver=LocalCrateSourceResolver(),
        validator=LocalCrateSourceValidator(),
        acquirer=LocalCrateSourceAcquirer(),
        file_system=file_system,
        copied_downloaded_crate_dir_name=settings.copied_downloaded_crate_dir_name,
        log_dir_name=settings.log_dir_name,
        results_dir_name=settings.results_dir_name,
    )

    inspect_service = DefaultInspectCrateService(
        parser=CrateMetadataParser(),
        normalizer=CrateMetadataNormalizer(),
        inspector=LocalPyCompssMetadataInspector(),
    )
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
        ImportCrateRequest(raw_source=args.source, workspace_directory=workspace_directory, crate_directory=shared_crate_directory,reuse_existing_crate=True)
    )
    view.print_import_result(import_result)

    inspect_result = view.run_with_spinner(
        "Inspecting crate metadata...",
        inspect_service.execute,
        InspectCrateRequest(crate_root=import_result.location.copied_downloaded_crate_path),
    )
    
    if inspect_result.crate is None:
        logger.info("final_status=invalid_crate_metadata")
        view.print_error("Could not build a usable crate summary from the metadata found.")
        return None, None
    
    crate = inspect_result.crate

    original_submission_command = plan_service._discover_command(crate)

    view.print_inspect_result(
        inspect_result,
        crate,
        original_submission_command,
    )

    if inspect_result.crate is None:
        logger.info("final_status=invalid_crate_metadata")
        view.print_error("Could not build a usable crate summary from the metadata found.")
        return None, None

    crate = inspect_result.crate

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

    # New: ask participant name only when provenance is enabled and interactive mode is active
    if provenance_flag and not args.yes:
        wants_name = view.console.input(
            "[yellow]Do you want to provide your name ? [y/N]: [/yellow]"
        ).lower().startswith("y")
        if wants_name:
            typed_name = Prompt.ask("[yellow]Write your name please:[/yellow]").strip()
            if typed_name:
                args.participant_name = typed_name
            if not typed_name:
                view.console.print("[yellow]Empty agent name provided, author's name will be used by default.[/yellow]")

    plan_result = _build_plan(args, plan_service, crate, workspace_directory, provenance_flag)
    logger.info(
        "resolved_command=%s backend=%s provenance_enabled=%s",
        plan_result.plan.command.as_string(),
        plan_result.plan.backend.value,
        provenance_flag,
    )
    view.console.print()
    view.console.print(f"Current submission command: {plan_result.plan.command.as_string()}")

    if not args.yes and view.console.input( "[yellow]Do you want to modify the submission command ? [y/N]: [/yellow]" ).lower().startswith("y"):
        plan_result = _update_plan_with_selected_flags( args=args, plan_service=plan_service, crate=crate, workspace_directory=workspace_directory, provenance_enabled=provenance_flag, current_plan=plan_result, logger=logger)

    view.print_execution_plan(plan_result.plan)

    if provenance_flag:
        provenance_result = provenance_service.execute(
            PrepareProvenanceRequest(
                crate=crate,
                provenance_root=plan_result.context.results_directory,
                participant_name=args.participant_name,
                participant_email=args.participant_email,
                participant_organization=args.participant_org,
                participant_orcid=args.participant_orcid,
                participant_ror=args.participant_ror,
            )
        )
        if provenance_result.provenance_config_file:
            logger.info("provenance_metadata=%s", provenance_result.provenance_config_file)
        view.print_provenance_result(provenance_result)

    return crate, plan_result


def _build_plan(
    args: argparse.Namespace,
    plan_service,
    crate,
    workspace_directory: Path,
    provenance_enabled: bool,
    submission_edits: tuple[SubmissionCommandEdit, ...] = (),
    ):
    backend = ExecutionBackend(args.backend)

    cli_extra_edits: list[SubmissionCommandEdit] = []
    for raw_flag in args.extra_flag:
        if "=" in raw_flag:
            name, value = raw_flag.split("=", 1)
            cli_extra_edits.append(
                SubmissionCommandEdit(
                    kind=SubmissionCommandEditKind.ADD,
                    name=name.strip(),
                    value=value.strip() or None,
                )
            )
        else:
            cli_extra_edits.append(
                SubmissionCommandEdit(
                    kind=SubmissionCommandEditKind.ADD,
                    name=raw_flag.strip(),
                    value=None,
                )
            )
    
    merged_edits = tuple(cli_extra_edits) + tuple(submission_edits)
    
    try:
        return plan_service.execute(
            BuildExecutionPlanRequest(
                crate=crate,
                workspace_directory=workspace_directory,
                backend=backend,
                provenance_enabled=provenance_enabled,
                submission_command=args.command,
                submission_edits=merged_edits,
            )
        )
    except BuildExecutionPlanFailure as exc:
        if args.yes or args.command:
            raise
    
        reason = str(exc).strip() or "unknown error"
        manual_command = Prompt.ask(
            "[yellow]Could not use the submission command from the crate "
            f"({reason}). Enter one manually (e.g. 'runcompss main.py')[/yellow]"
        )
        return plan_service.execute(
            BuildExecutionPlanRequest(
                crate=crate,
                workspace_directory=workspace_directory,
                backend=backend,
                provenance_enabled=provenance_enabled,
                submission_command=manual_command,
                submission_edits=merged_edits,
            )
        )

def _build_run_logger(workspace_directory: Path) -> logging.Logger:
    log_dir = workspace_directory / "log"
    log_dir.mkdir(parents=True, exist_ok=True)

    logger = logging.getLogger(f"reproducibility_service.{workspace_directory.name}")
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
    workspace_directory: Path,
    provenance_enabled: bool,
    current_plan,
    logger: logging.Logger,
):
    raw_edits = view.edit_submission_command(
        current_plan.plan.backend,
        current_plan.plan.command.as_list(),
    )
    if raw_edits is None:
        return current_plan

    normalized_edits: list[SubmissionCommandEdit] = []
    for edit in raw_edits:
        kind_value = edit.kind.value if hasattr(edit.kind, "value") else str(edit.kind)
        normalized_edits.append(
            SubmissionCommandEdit(
                kind=SubmissionCommandEditKind(kind_value),
                name=edit.name,
                value=edit.value,
            )
        )

    args.command = current_plan.plan.command.as_string()
    args.extra_flag = []

    plan_result = _build_plan(
        args,
        plan_service,
        crate,
        workspace_directory,
        provenance_enabled,
        submission_edits=tuple(normalized_edits),
    )
    logger.info(
        "resolved_command=%s backend=%s provenance_enabled=%s",
        plan_result.plan.command.as_string(),
        plan_result.plan.backend.value,
        provenance_enabled,
    )
    return plan_result

PROVENANCE_FLAGS = {"--provenance", "-p"}

def main() -> None:
    raise SystemExit(run_app())


if __name__ == "__main__":
    main()