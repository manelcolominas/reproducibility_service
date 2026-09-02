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

from application.use_cases.inspect_crate import (
    _inspect_rocrate
)
from application.use_cases.prepare_provenance import (
    DefaultPrepareProvenanceService,
    PrepareProvenanceRequest,
)

from config.settings import AppSettings, build_default_settings
from domain.errors import ServiceError
from domain.models.execution import ExecutionBackend
from infrastructure.adapters import (
    LocalFileSystem,
    ShutilExecutionBackendDetector,
    SubprocessExecutionAgent,
)

from application.use_cases.import_crate import (
    _import_rocrate,
)

from application.use_cases.inspect_crate import (
    _verify_rocrate,
)

from presentation.cli import view

def build_arg_parser() -> argparse.ArgumentParser:
    # creates and configures the command-line argument parser for the reproducibility service,
    # defining which inputs the user can provide and how those inputs are parsed into attributes
    #  that the application uses during execution.
    # the library ArgumentParser is used to create command line interfaces. It automatically generates help and usage messages and issues errors when users give the program invalid arguments.
    parser = argparse.ArgumentParser(
        prog="reproducibility_service",
        description="Reproduce a COMPSs workflow run from an RO-Crate.",
    )
    # the source is a positional argument, can be a local directory, a .zip file, or a URL
    # the source is a positional argument, it is mandatory and does not require a flag, doesn't begin with a dash (- or --). The user must provide it when running the command.
    parser.add_argument("source", help="Local directory, .zip file, or URL of the RO-Crate")

        
    # Add a flag to allow the user to specify a run identifier. This flag is optional and can be used to provide a custom identifier for the workflow run. If not provided, a random identifier will be generated based on the current timestamp.
    parser.add_argument("--run-id", help="Identifier for this run (default: random)")

    # Add a flag to allow the user to specify the execution backend. The choices are "auto", "local", or "slurm". The default is "auto". This flag is optional and can be used to override the default backend detected from the crate metadata.
    parser.add_argument("--backend", choices=["auto", "local", "slurm"], default="auto", help="Execution backend")

    # Add a flag to allow the user to specify a custom COMPSs submission command. This flag is optional and can be used to override the default command discovered from the crate metadata.
    parser.add_argument("--command", help="Override the COMPSs submission command line")

    # Add a flag to allow the user to specify extra runtime flags for the COMPSs submission command. This flag is optional and can be repeated multiple times to add multiple flags.
    parser.add_argument("--extra-flag", action="append", default=[], help="Extra runtime flag (repeatable)")

    # Add a flag to enable provenance. This flag is optional and can be used to enable provenance tracking for the workflow run.
    parser.add_argument("--provenance", "-p", action="store_true", help="Enable provenance and write ro-crate-info.yaml")
    parser.add_argument("--participant-name", default=None)
    parser.add_argument("--participant-email")
    parser.add_argument("--participant-org")
    parser.add_argument("--participant-orcid")
    parser.add_argument("--participant-ror")

    # Add a flag to skip confirmation prompts, useful for non-interactive runs or automated scripts.
    parser.add_argument("-y", "--yes", action="store_true", help="Skip confirmation prompts")
    return parser

def run_app(argv: list[str] | None = None) -> int:
    # build_arg_parser() creates and configures the ArgumentParser, defining which
    # command-line arguments are accepted by the program.
    
    # parse_args(argv) then parses the arguments contained in argv and returns a
    # Namespace object with the parsed command line arguments,

    # for example, if the user runs the command:
    # reproducibility_service workflow-635-1.crate.zip --backend slurm --provenance --participant-name "John Doe" --participant-email "john.doe@example.com" --participant-org "Example Org" --participant-orcid "0000-0001-2345-6789" --participant-ror "https://ror.org/123456789"
    # the argv list will contain the following elements:
    # remember that source is positional argument, so it doesn't have a flag, and the rest are optional arguments with flags.
    # ['workflow-635-1.crate.zip', '--backend', 'slurm', '--provenance', '--participant-name', 'John Doe', '--participant-email', 'john.doe@example.com', '--participant-org', 'Example Org', '--participant-orcid', '0000-0001-2345-6789', '--participant-ror', 'https://ror.org/123456789']

    # parse_args(argv) will then parse these arguments and return a Namespace object with the following attributes:
    # Namespace(source='workflow-635-1.crate.zip', backend='slurm', command=None, extra_flag=[], provenance=True, participant_name='John Doe', participant_email='john.doe@example.com', participant_org='Example Org', participant_orcid='0000-0001-2345-6789', participant_ror='https://ror.org/123456789', yes=False)
    # The values can then be accessed in the code using attributes such as:
    # `args.source`, `args.backend`, `args.command`, `args.participant_name`, `args.participant_email`, `args.participant_org`, `args.participant_orcid`, `args.participant_ror`, `args.yes`, etc.
    args = build_arg_parser().parse_args(argv)

    # Build an AppSettings object with the default settings for the application, which includes
    # the default_backend = "auto", log_dir_name="log", results_dir_name="Results", submission_filename="compss_submission_command_line.txt",
    #  metadata_filename="ro-crate-metadata.json", original_crate_dir_name="", runs_root = /opt/COMPSs/Tools, and service_root= /opt/COMPSs/Tools.
    settings = build_default_settings()

    # if was not provided a run_id by the user, generate a run_id based on the current timestamp in the format YYYYMMDD_HHMMSS.
    # if the user provides a run_id, use that instead.
    run_id = args.run_id or datetime.now().strftime("%Y%m%d_%H%M%S")

    # take the source argument provided by the user.
    source_arg = args.source.strip()
    # if the source argument starts with "http://" or "https://", it is considered a URL, otherwise it is considered a local path.
    source_is_url = source_arg.startswith(("http://", "https://"))

    # if the source is a URL,
    if source_is_url:
        # runs_root is the directory where is executed the reproducibility service, and shared_crate_directory 
        # takes the current working where the reproducibility service is launched.
        runs_root = Path.cwd()
        # a hidden directory named ".crate_downloaded" is created temporarily in the runs_root to store the downloaded crate from the URL.
        shared_crate_directory = runs_root / "crate_downloaded_provisional_name"

    # if the source is a local path or zip file.
    else:
        # source_arg = workflow-635-1.crate
        # source_path = /home/mcolomin/Desktop/bsc-wdc/codi_compss/proves/635/workflow-635-1.crate
        # returns the absolute path of the source argument.
        source_path = Path(source_arg).expanduser().resolve()

        # source_path = /home/mcolomin/Desktop/bsc-wdc/codi_compss/proves/635/workflow-635-1.crate
        # runs_root = /home/mcolomin/Desktop/bsc-wdc/codi_compss/proves/635
        # it takes the parent directory of the source path,
        runs_root = source_path.parent

        # if the source_path is a zip file.
        # source_path = /home/mcolomin/Desktop/bsc-wdc/codi_compss/proves/635/workflow-635-1.crate.zip
        if source_path.suffix.lower() == ".zip":
            # builds the path (just in the code, doesn't extract the zip file) of the shared_crate_directory by removing the .zip suffix from the source_path.
            # for example, if the source_path is /home/mcolomin/Desktop/bsc-wdc/codi_compss/proves/635/workflow-635-1.crate.zip, 
            # the shared_crate_directory will be /home/mcolomin/Desktop/bsc-wdc/codi_compss/proves/635/workflow-635-1.crate
            shared_crate_directory = source_path.with_suffix("")

        # if the source_path is not a zip file, it is considered a directory,
        # the shared_crate_directory is set to the source_path itself.
        # source_path = /home/mcolomin/Desktop/bsc-wdc/codi_compss/proves/635/workflow-635-1.crate.zip
        else:
            # the shared_crate_directory is set to the source_path itself.
            shared_crate_directory = source_path

    # workspace_directory is the directory where the reproducibility service will create its workspace for this run,
    # and it is constructed by joining the runs_root with a prefix and the reproducibility_service_{run_id}.
    # just build the path in the code, doesn't create the directory yet.
    workspace_directory = runs_root / f"reproducibility_service_{run_id}"

    # create the workspace_directory (reproducibility service {run_id} )
    workspace_directory.mkdir(parents=True, exist_ok=True)

    # build a logger for the reproducibility service run, which will log messages
    # to a rs_log.txt in the workspace_directory/log directory (reproducibility_service_{run_id}/log/rs_log.txt).
    logger = _build_run_logger(workspace_directory)

    # log the source argument provided by the user, which can be a local directory, a .zip file, or a URL.
    # this line will add an entry to the log file with the source argument, for example:
    # 2026-08-20 16:47:40,808 INFO source=workflow-635-1.crate.zip
    logger.info("source=%s", args.source)

    #1. print the banner of the reproducibility service, which is the name of the service and a little description of it.
    # ╭──────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────╮
    # │                                                      COMPSs Reproducibility Service                                                      │
    # ╰──────────────────────────────────────────── reproduce a COMPSs workflow run from an RO-Crate ────────────────────────────────────────────╯
    view.print_banner()

    # try to run the pipeline of the reproducibility service,
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

    agent = SubprocessExecutionAgent()
    outcome = view.run_with_spinner("Executing workflow...", agent.submit, plan_result.submission)
    view.print_final_summary(outcome)

    logger.info(
        "final_status=%s return_code=%s",
        "succeeded" if outcome.succeeded else "failed",
        outcome.result.return_code,
    )
    return 0 if outcome.succeeded else 1

def _run_pipeline( args: argparse.Namespace, settings: AppSettings, workspace_directory: Path, shared_crate_directory: Path, logger: logging.Logger ):
    """
    Runs the pipeline of the reproducibility service.

    Args:
        args: A Namespace object containing the command-line arguments. args = Namespace(source='workflow-635-1.crate.zip', backend='slurm', command=None, extra_flag=[], provenance=True, participant_name='John Doe', participant_email='john.doe@example.com', participant_org='Example Org', participant_orcid='0000-0001-2345-6789', participant_ror='https://ror.org/123456789', yes=False)
        settings: An AppSettings object containing the application settings. settings = AppSettings(service_root=PosixPath('/opt/COMPSs/Tools'), runs_root=PosixPath('/opt/COMPSs/Tools'), original_crate_dir_name='', log_dir_name='log', results_dir_name='Results', submission_filename='compss_submission_command_line.txt', metadata_filename='ro-crate-metadata.json', default_backend='auto', enable_provenance_by_default=False)
        workspace_directory: The workspace directory path. (/home/mcolomin/Desktop/bsc-wdc/codi_compss/proves/635/reproducibility_service_{run_id})
        shared_crate_directory: The shared crate directory path. (/home/mcolomin/Desktop/bsc-wdc/codi_compss/proves/635/workflow-635-1.crate)
        logger: The logger instance of the reproducibility service run.

    Returns:
        A tuple containing the crate and the plan result.

    Raises:
        ServiceError: If an error occurs during the pipeline execution.
    """

    # create a LocalFileSystem instance to handle file system operations, exists, metadata, write_text, create_directrory
    file_system = LocalFileSystem()

    # calls the _import_rocrate function to import the RO-Crate from the source provided by the user
    # the function will return an ImportCrateResult object containing the imported crate and its location
    # import_result = ImportCrateResult(
    #     source=source_with_rocrate,
    #     validation=validation,
    #     acquisition=acquisition,
    #     crate_location=crate_location,
    #     crate=crate,
    #     notes=("Crate source prepared successfully",),
    # )
    import_result = _import_rocrate(args.source, workspace_directory, shared_crate_directory, file_system)

    # ╭─ 1. Crate source imported ──────────────────────────────────────────────────────────────────────────────────────────────────────────╮
    # │ Source type   zip                                                                                                                   │
    # │ Source name   workflow-635-1.crate.zip                                                                                              │
    # │ Ro-Crate path /home/mcolomin/Desktop/bsc-wdc/codi_compss/proves/635/workflow-635-1.crate                                            │
    # ╰─────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────╯
    
    view.print_import_result(import_result)

    # calls the _inspect_rocrate function to inspect the imported RO-Crate
    # the function will return an InspectCrateResult object containing the crate and its metadata
    inspect_result = _inspect_rocrate(import_result)

    if inspect_result.import_crate_result is None:
        logger.info("final_status=invalid_crate_metadata")
        view.print_error("Could not build a usable crate summary from the metadata found.")
        return None, None

    plan_service = DefaultBuildExecutionPlanService(
        backend_detector=ShutilExecutionBackendDetector(),
        log_dir_name=settings.log_dir_name,
        results_dir_name=settings.results_dir_name,
    )

    original_submission_command = plan_service._discover_command(inspect_result.import_crate_result.crate_location)

    # ╭─ 2. Metadata inspected ───────────────────────────────────────────────────────────────────╮
    # │ ───────────────────────────── RO-Crate Inspection ──────────────────────────────          │
    # │ CRATE                                                                                     │
    # │ /home/mcolomin/Desktop/bsc-wdc/codi_compss/proves/635/workflow-635-1.crate/ro-cr          │
    # │ ate-metadata.json                                                                         │
    # │ ├── Name —— PyCOMPSs Wordcount test, using files                                          │
    # │ ├── Description —— **Name:** Word Count                                                   │
    #       ·                                      ·                                        ·
    #       ·                                      ·                                        ·       
    #       ·                                      ·                                        ·                       
    # │ ├── Authors                                                                               │
    # │ │   └── Javier Conejero (Barcelona Supercomputing Center)                                 │
    # │ │       (francisco.conejero@bsc.es)                                                       │
    # │ ├── License —— Apache-2.0                                                                 │
    # │ ├── Date Published —— Thursday, 02 of November of 2023 - 10:55 UTC                        │
    # │ ├── Main entity —— application_sources/src/wordcount.py                                   │
    # │ │   └── Programming language —— COMPSs Programming Model (3.2.rc2310)                     │
    # │ └── Execution details                                                                     │
    # │     ├── Status —— COMPLETED                                                               │
    # │     ├── Host —— marenostrum4 —— Job ID —— 30498188                                        │
    # │     ├── Agent —— Raül Sirvent (Barcelona Supercomputing Center)                           │
    # │     │   (Raul.Sirvent@bsc.es)                                                             │
    # │     └── Data assets —— 4 Inputs —— 1 Outputs                                              │
    # │ ────────────────────────────────────────────────────────────────────────────────          │
    # │ Submission command enqueue_compss --provenance --num_nodes=1 --qos=debug                  │
    # │                    --job_name=wordcount_files --lang=python --log_level=debug --summary   │
    # │                    --exec_time=5                                                          │
    # │                    /home/bsc19/bsc19057/COMPSs-DP/tutorial_apps/python/wordcount/src/wor… │
    # │                    /home/bsc19/bsc19057/COMPSs-DP/tutorial_apps/python/wordcount/data/    │
    # │ Data persistence   true                                                                   │
    # ╰───────────────────────────────────────────────────────────────────────────────────────────╯

    view.print_inspect_result(inspect_result, original_submission_command)

    verify_result = _verify_rocrate(inspect_result, file_system)
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

    if provenance_flag and not args.yes:
        wants_name = view.console.input(
            "[yellow]Do you want to provide your name ? [y/N]: [/yellow]"
        ).lower().startswith("y")
        if wants_name:
            typed_name = Prompt.ask("[yellow]Write your name please:[/yellow]").strip()
            if typed_name:
                args.participant_name = typed_name
            else:
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

    if not args.yes and view.console.input(
        "[yellow]Do you want to modify the submission command ? [y/N]: [/yellow]"
    ).lower().startswith("y"):
        plan_result = _update_plan_with_selected_flags(
            args=args,
            plan_service=plan_service,
            crate=crate,
            workspace_directory=workspace_directory,
            provenance_enabled=provenance_flag,
            current_plan=plan_result,
            logger=logger,
        )

    view.print_execution_plan(plan_result.plan)

    if provenance_flag:
        provenance_service = DefaultPrepareProvenanceService(file_system=file_system)
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
    # create the path for the log directory
    log_dir = workspace_directory / "log"

    # create the log directory, if it doesn't exist, and create any missing parent directories.
    log_dir.mkdir(exist_ok=True, parents=True)

    # create or retrieve a logger object for the reproducibility service run with the name of the
    # workspace_directory (reproducibility_service_{run_id}), which makes that every execution
    # have its own logger.
    logger = logging.getLogger(f"reproducibility_service.{workspace_directory.name}")

    # set the logger level to INFO, which means that all messages with a severity level of INFO or higher will be logged.
    logger.setLevel(logging.INFO)

    # to avoid propagating log messages to upper level loggers (e.g., the root logger or reproducibility_service logger), which could 
    # result in duplicate log entries, set the propagate attribute of the logger to False.
    logger.propagate = False

    # check if the logger already has a FileHandler.
    # logger.handlers is a list of all the handlers attached to the logger. A handler is an object that determines
    # how log messages are processed and where they are sent (e.g., to a file, to the console, etc.).
    if not any(isinstance(handler, logging.FileHandler) for handler in logger.handlers):
        # create a FileHandler that writes log messages to a file named "rs_log.txt" in the log directory, with UTF-8 encoding.
        file_handler = logging.FileHandler(log_dir / "rs_log.txt", encoding="utf-8")
        # set the log message format for the FileHandler to include the timestamp, log level, and the message.
        file_handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
        # add the FileHandler to the logger, so that log messages are written to the file.
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

def main() -> None:
    raise SystemExit(run_app(None))


if __name__ == "__main__":
    main()