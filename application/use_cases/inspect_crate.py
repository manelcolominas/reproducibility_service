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
import os
import pty
import subprocess
from pathlib import Path

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum

from application.ports.metadata_parser import (
    WorkflowMetadata,
    
)
from infrastructure.adapters import (
    CrateMetadataParser,
    CrateMetadataNormalizer,
)
from domain.errors import ValidationError
from application.use_cases.import_crate import ImportCrateResult
from domain.models.crate import WorkflowArtifactSummary


class InspectCrateStatus(str, Enum):
    SUCCEEDED = "succeeded"
    FAILED = "failed"

@dataclass(frozen=True, slots=True)
class InspectCrateResult:
    status: InspectCrateStatus
    normalization:  None = None
    verification: WorkflowArtifactSummary | None = None
    warnings: tuple[str, ...] = ()
    notes: tuple[str, ...] = ()
    inspect_output: str | None = None
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    @property
    def inspected(self) -> bool:
        return self.status == InspectCrateStatus.SUCCEEDED

    @property
    def has_warnings(self) -> bool:
        return len(self.warnings) > 0


class LocalPyCompssMetadataInspector:
    """Runs pycompss inspect on the crate metadata source using a PTY so Rich keeps colors."""

    def __init__(self, executable: str = "pycompss") -> None:
        self._executable = executable

    def inspect(self, ) -> :
        if document.format == RO_CRATE_JSON and document.path is not None:
            target = document.path.parent
        elif document.format == COMPSS_YAML and document.path is not None:
            target = document.path
        else:
            target = Path(document.source.location)
        # if you want the verbose output
        #command = [self._executable, "inspect", "-v", str(target)]
        command = [self._executable, "inspect", str(target)]

        try:
            master_fd, slave_fd = pty.openpty()
        except OSError as exc:
            return (
                ok=False,
                warning=f"pycompss inspect PTY allocation failed: {exc}",
            )

        try:
            process = subprocess.Popen(command, stdin=slave_fd, stdout=slave_fd, stderr=slave_fd, close_fds=True)
        except FileNotFoundError:
            os.close(master_fd)
            os.close(slave_fd)
            return (ok=False, warning="pycompss inspect unavailable: executable 'pycompss' not found")
        except OSError as exc:
            os.close(master_fd)
            os.close(slave_fd)
            return (ok=False, warning=f"pycompss inspect could not be executed: {exc}")

        os.close(slave_fd)

        chunks: list[bytes] = []
        try:
            while True:
                try:
                    data = os.read(master_fd, 4096)
                except OSError:
                    break
                if not data:
                    break
                chunks.append(data)
        finally:
            try:
                os.close(master_fd)
            except OSError:
                pass

        return_code = process.wait()
        output = b"".join(chunks).decode("utf-8", errors="replace").rstrip()

        if return_code == 0:
            return ( ok=True, stdout=output or None)

        details = output or "no diagnostic output"
        return ( ok=False, stdout=output or None, warning=f"pycompss inspect failed (exit code {return_code}): {details}" )


def _inspect_rocrate(import_crate_result: ImportCrateResult) -> InspectCrateResult:

        return InspectCrateResult(
            status=
            normalization=
            warnings=
            notes=
            inspect_output=
        )