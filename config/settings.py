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

from dataclasses import dataclass, replace
from pathlib import Path


@dataclass(frozen=True, slots=True)
class AppSettings:
    service_root: Path
    runs_root: Path
    workflow_dir_name: str = "Workflow"
    log_dir_name: str = "log"
    results_dir_name: str = "Result"
    submission_filename: str = "compss_submission_command_line.txt"
    metadata_filename: str = "ro-crate-metadata.json"
    default_backend: str = "auto"
    enable_provenance_by_default: bool = False

    def __post_init__(self) -> None:
        if not str(self.service_root).strip():
            raise ValueError("service_root cannot be empty")
        if not str(self.runs_root).strip():
            raise ValueError("runs_root cannot be empty")
        if not self.workflow_dir_name.strip():
            raise ValueError("workflow_dir_name cannot be empty")
        if not self.log_dir_name.strip():
            raise ValueError("log_dir_name cannot be empty")
        if not self.results_dir_name.strip():
            raise ValueError("results_dir_name cannot be empty")
        if not self.submission_filename.strip():
            raise ValueError("submission_filename cannot be empty")
        if not self.metadata_filename.strip():
            raise ValueError("metadata_filename cannot be empty")
        if self.default_backend not in {"auto", "local", "slurm"}:
            raise ValueError("default_backend must be auto, local, or slurm")

    @property
    def run_prefix(self) -> str:
        return "reproducibility_service_"

    def run_directory(self, run_id: str) -> Path:
        if not run_id.strip():
            raise ValueError("run_id cannot be empty")
        return self.runs_root / f"{self.run_prefix}{run_id}"

    def workflow_root(self, run_directory: Path) -> Path:
        return run_directory / self.workflow_dir_name

    def log_directory(self, run_directory: Path) -> Path:
        return run_directory / self.log_dir_name

    def results_directory(self, run_directory: Path) -> Path:
        return run_directory / self.results_dir_name

    def with_default_backend(self, backend: str) -> AppSettings:
        return replace(self, default_backend=backend)


def build_default_settings(service_root: Path | None = None) -> AppSettings:
    root = service_root or Path(__file__).resolve().parents[2]
    return AppSettings(
        service_root=root,
        runs_root=root,
    )