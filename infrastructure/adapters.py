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

from importlib.resources import path
import os
import subprocess
import pty
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable
import shutil
import struct
import fcntl
import termios

import yaml

from application.ports.file_system import (
    FileSystemOperationResult,
)
from domain.models.crate import (
    EntityKind,
    WorkflowEntity,
    WorkflowMetadata,
    WorkflowParticipant,
)
from domain.models.execution import (
    ExecutionContext,
    ExecutionLog,
    ExecutionResult,
    ExecutionStatus,
    ExecutionSubmission,
    ExecutionOutcome
)

# --------------------------------------------------------------------------- #
# File system adapter
# --------------------------------------------------------------------------- #


class LocalFileSystem:
    """
        The LocalFileSystem class provides an interface for managing files and directories
        on the local filesystem. It uses Python's pathlib, shutil, and os modules to perform
        common filesystem operations, such as checking whether a file or directory exists,
        writing files, creating directories, files
        and directories. It also provides methods for retrieving file metadata and manipulating
        paths. The class acts as an abstraction layer, allowing the rest of the application to
        interact with the local filesystem without directly depending on the underlying filesystem
        operations.
    """

    # verify if a path exists
    def exists(self, path: Path) -> bool:
        return Path(path).exists()
    
    def create_directory(self, path: Path, parents: bool, exist_ok: bool) -> FileSystemOperationResult:
        """
        Creates a directory at the specified path.

        Parameters:
            path (Path): The path of the directory to create.
            parents (bool): Whether to create parent directories if they do not exist.
            exist_ok (bool): Whether to ignore the error if the directory already exists.

        Returns:
            FileSystemOperationResult: The status of the directory creation operation.
            
            class FileSystemOperationResult:
                path: Path The path on which the operation was performed.
                succeeded: bool Whether the operation succeeded.
                message: str = "" An optional message providing additional information about the operation.
                bytes_transferred: int | None = None The number of bytes transferred during the operation, if applicable.
        """
        try:
            Path(path).mkdir(parents=parents, exist_ok=exist_ok)
            return FileSystemOperationResult(path=path, succeeded=True)
        except OSError as exc:
            return FileSystemOperationResult(path=path, succeeded=False, message=str(exc))

    def write_text(self, path: Path, content: str, encoding: str = "utf-8") -> FileSystemOperationResult:
        path = Path(path)
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(content, encoding=encoding)
            return FileSystemOperationResult(path=path, succeeded=True, bytes_transferred=len(content))
        except OSError as exc:
            return FileSystemOperationResult(path=path, succeeded=False, message=str(exc))

    def get_size(self, path: Path) -> int:
        size_in_bytes = path.stat().st_size
        return size_in_bytes

### DO NOT DELETE
class SubprocessExecutionAgent:
    """Runs the built COMPSs command as a local subprocess, streaming its output."""

    def __init__(self, logger: logging.Logger | None = None) -> None:
        self._logger = logger

    def submit(
        self,
        submission: ExecutionSubmission,
        on_output: Callable[[bytes], None] | None = None,
    ) -> ExecutionOutcome:
        started_at = datetime.now(timezone.utc)
        if self._logger is not None:
            self._logger.info(
                "subprocess_preparing command=%s working_directory=%s",
                submission.command.as_list(),
                submission.command.working_directory or submission.execution_directory or submission.workspace_directory,
            )
        submission.workspace_directory.mkdir(parents=True, exist_ok=True)
        submission.log_directory.mkdir(parents=True, exist_ok=True)
        submission.results_directory.mkdir(parents=True, exist_ok=True)

        # COMPSs output is line-buffered by a PTY so ANSI colors survive; stdout/stderr share one stream.
        stdout_path = submission.log_directory / "log.out"
        stderr_path = stdout_path
        return_code: int | None = None
        error_message: str | None = None

        try:
            master_fd, slave_fd = pty.openpty()
            terminal_size = shutil.get_terminal_size(fallback=(120, 40))
            winsize = struct.pack("HHHH", terminal_size.lines, terminal_size.columns, 0, 0)
            fcntl.ioctl(slave_fd, termios.TIOCSWINSZ, winsize)
        except OSError as exc:
            status = ExecutionStatus.FAILED
            error_message = f"PTY allocation failed: {exc}"
            if self._logger is not None:
                self._logger.exception("subprocess_failed error=%s", error_message)
            return self._build_outcome(submission, started_at, status, None, error_message, stdout_path, stderr_path)

        working_directory = str(submission.command.working_directory or submission.execution_directory or submission.workspace_directory)

        try:
            if self._logger is not None:
                self._logger.info("subprocess_output_file path=%s", stdout_path)
            process = subprocess.Popen(
                submission.command.as_list(),
                cwd=working_directory,
                stdin=slave_fd,
                stdout=slave_fd,
                stderr=slave_fd,
                close_fds=True,
            )
        except FileNotFoundError as exc:
            os.close(master_fd)
            os.close(slave_fd)
            status = ExecutionStatus.FAILED
            error_message = f"Executable not found: {exc.filename or submission.command.executable}"
            if self._logger is not None:
                self._logger.exception("subprocess_failed error=%s", error_message)
            return self._build_outcome(submission, started_at, status, None, error_message, stdout_path, stderr_path)
        except OSError as exc:
            os.close(master_fd)
            os.close(slave_fd)
            status = ExecutionStatus.FAILED
            error_message = str(exc)
            if self._logger is not None:
                self._logger.exception("subprocess_failed error=%s", error_message)
            return self._build_outcome(submission, started_at, status, None, error_message, stdout_path, stderr_path)

        os.close(slave_fd)

        with open(stdout_path, "wb") as log_file:
            try:
                while True:
                    try:
                        data = os.read(master_fd, 4096)
                    except OSError:
                        break
                    if not data:
                        break
                    log_file.write(data)
                    log_file.flush()
                    if on_output is not None:
                        on_output(data)
            finally:
                try:
                    os.close(master_fd)
                except OSError:
                    pass

        return_code = process.wait()
        status = ExecutionStatus.SUCCEEDED if return_code == 0 else ExecutionStatus.FAILED
        if return_code != 0:
            error_message = f"Process exited with code {return_code}"
        if self._logger is not None:
            self._logger.info("subprocess_finished return_code=%s status=%s", return_code, status.value)

        return self._build_outcome(submission, started_at, status, return_code, error_message, stdout_path, stderr_path)

    def _build_outcome(self, submission, started_at, status, return_code, error_message, stdout_path, stderr_path) -> ExecutionOutcome:
        finished_at = datetime.now(timezone.utc)
        context = ExecutionContext(backend=submission.backend, workspace_directory=submission.workspace_directory, log_directory=submission.log_directory, results_directory=submission.results_directory)
        log = ExecutionLog(stdout_path=stdout_path, stderr_path=stderr_path)
        generated_ro_crate_path = self.find_generated_ro_crate_path(submission)
        if self._logger is not None:
            self._logger.info(
                "subprocess_result status=%s return_code=%s duration_seconds=%.3f generated_ro_crate=%s",
                status.value, return_code, (finished_at - started_at).total_seconds(), generated_ro_crate_path,
            )
        result = ExecutionResult(status=status, command=submission.command, context=context, log=log, return_code=return_code, started_at=started_at, finished_at=finished_at, summary_message="Execution succeeded" if status == ExecutionStatus.SUCCEEDED else "Execution failed", error_message=error_message, generated_ro_crate_path=generated_ro_crate_path)
        return ExecutionOutcome(result=result, submission=submission)

    def find_generated_ro_crate_path(self, submission: ExecutionSubmission) -> Path:
        generated_ro_crate_path = None
        for candidate in sorted(submission.results_directory.rglob("COMPSs_RO-Crate*"), key=lambda p: p.stat().st_mtime if p.exists() else 0.0, reverse=True):
            if candidate.is_dir() or candidate.is_file():
                generated_ro_crate_path = candidate.resolve()
                break
        if self._logger is not None:
            self._logger.info("generated_ro_crate_search results_directory=%s found=%s", submission.results_directory, generated_ro_crate_path)
        return generated_ro_crate_path