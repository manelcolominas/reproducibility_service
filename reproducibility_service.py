#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import shlex
import shutil
import subprocess
import sys
import threading
import urllib.request
import zipfile
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Iterable


RUN_PREFIX = "reproducibility_service_"
LOG_DIR_NAME = "log"
RESULTS_DIR_NAME = "Results"
CRATE_METADATA_FILE = "ro-crate-metadata.json"
SUBMISSION_FILE = "compss_submission_command_line.txt"
COMPSS_EXECUTABLES = ("runcompss", "enqueue_compss")


@dataclass(frozen=True)
class RunWorkspace:
    root: Path
    crate_root: Path
    log_dir: Path
    results_dir: Path


def timestamp() -> str:
    return datetime.now().strftime("%Y%m%d_%H%M%S")


def detect_backend() -> str:
    try:
        result = subprocess.run(["squeue"], capture_output=True, text=True)
        return "slurm" if result.returncode == 0 else "local"
    except Exception:
        return "local"


def create_workspace(base_dir: Path) -> RunWorkspace:
    root = base_dir / f"{RUN_PREFIX}{timestamp()}"
    crate_root = root / "crate"
    log_dir = root / LOG_DIR_NAME
    results_dir = root / RESULTS_DIR_NAME

    root.mkdir(parents=True, exist_ok=False)
    crate_root.mkdir(parents=True, exist_ok=True)
    log_dir.mkdir(parents=True, exist_ok=True)
    results_dir.mkdir(parents=True, exist_ok=True)

    return RunWorkspace(
        root=root,
        crate_root=crate_root,
        log_dir=log_dir,
        results_dir=results_dir,
    )


def source_kind(raw_source: str) -> str:
    if raw_source.startswith(("http://", "https://")):
        return "url"
    if zipfile.is_zipfile(raw_source):
        return "zip"
    if Path(raw_source).is_dir():
        return "directory"
    return "path"


def download_file(url: str, destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    urllib.request.urlretrieve(url, destination)


def copy_tree(source: Path, destination: Path) -> None:
    if source.is_dir():
        for item in source.iterdir():
            target = destination / item.name
            if item.is_dir():
                target.mkdir(parents=True, exist_ok=True)
                copy_tree(item, target)
            else:
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(item, target)
    else:
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, destination)


def extract_archive(archive: Path, destination: Path) -> None:
    with zipfile.ZipFile(archive, "r") as zip_ref:
        zip_ref.extractall(destination)


def normalize_crate_root(root: Path) -> Path:
    if (root / CRATE_METADATA_FILE).exists() or (root / SUBMISSION_FILE).exists():
        return root

    for candidate in root.rglob(CRATE_METADATA_FILE):
        return candidate.parent

    for candidate in root.rglob(SUBMISSION_FILE):
        return candidate.parent

    raise SystemExit(
        f"Could not find {CRATE_METADATA_FILE} or {SUBMISSION_FILE} under {root}"
    )


def acquire_source(raw_source: str, crate_destination: Path) -> Path:
    kind = source_kind(raw_source)

    if kind == "url":
        archive = crate_destination.parent / "source.zip"
        download_file(raw_source, archive)
        extract_archive(archive, crate_destination)
    elif kind == "zip":
        extract_archive(Path(raw_source), crate_destination)
    elif kind in {"directory", "path"} and Path(raw_source).exists():
        copy_tree(Path(raw_source), crate_destination)
    else:
        raise SystemExit(f"Unsupported source: {raw_source}")

    return normalize_crate_root(crate_destination)


def walk_strings(node: object) -> Iterable[str]:
    if isinstance(node, dict):
        for value in node.values():
            yield from walk_strings(value)
    elif isinstance(node, list):
        for item in node:
            yield from walk_strings(item)
    elif isinstance(node, str):
        yield node


def discover_submission_command(crate_root: Path) -> list[str]:
    submission_file = crate_root / SUBMISSION_FILE
    if submission_file.exists():
        content = submission_file.read_text(encoding="utf-8").strip()
        if content:
            return shlex.split(content)

    metadata_file = crate_root / CRATE_METADATA_FILE
    if metadata_file.exists():
        try:
            data = json.loads(metadata_file.read_text(encoding="utf-8"))
            for candidate in walk_strings(data):
                if candidate.startswith(COMPSS_EXECUTABLES):
                    return shlex.split(candidate)
        except Exception as exc:
            raise SystemExit(f"Could not parse {metadata_file}: {exc}") from exc

    raise SystemExit(
        f"Could not discover a COMPSs command in {crate_root}. "
        f"Expected {SUBMISSION_FILE} or a description in {CRATE_METADATA_FILE}."
    )


def choose_runtime(backend: str) -> str:
    if backend == "slurm":
        return "enqueue_compss"
    return "runcompss"


def build_command(
    crate_root: Path,
    backend: str,
    provenance: bool,
    extra_flags: list[str],
) -> list[str]:
    command = discover_submission_command(crate_root)
    if not command:
        raise SystemExit("Empty submission command")

    command[0] = choose_runtime(backend)

    insertion_index = 1
    if provenance:
        command.insert(insertion_index, "--provenance")
        insertion_index += 1

    for flag in extra_flags:
        command.insert(insertion_index, flag)
        insertion_index += 1

    return command


def run_command(command: list[str], cwd: Path, log_dir: Path) -> int:
    stdout_log = log_dir / "out.log"
    stderr_log = log_dir / "err.log"

    process = subprocess.Popen(
        command,
        cwd=str(cwd),
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        bufsize=1,
    )

    assert process.stdout is not None
    assert process.stderr is not None

    def tee(pipe, target_path: Path) -> None:
        with target_path.open("w", encoding="utf-8") as target:
            for line in iter(pipe.readline, ""):
                print(line, end="")
                target.write(line)
                target.flush()
        pipe.close()

    stdout_thread = threading.Thread(target=tee, args=(process.stdout, stdout_log))
    stderr_thread = threading.Thread(target=tee, args=(process.stderr, stderr_log))

    stdout_thread.start()
    stderr_thread.start()
    process.wait()
    stdout_thread.join()
    stderr_thread.join()

    print(f"stdout log: {stdout_log}")
    print(f"stderr log: {stderr_log}")
    return process.returncode


def move_new_outputs(crate_root: Path, results_dir: Path, before: set[str]) -> None:
    results_dir.mkdir(parents=True, exist_ok=True)

    for item in crate_root.iterdir():
        if item.name in before:
            continue
        if item.name in {LOG_DIR_NAME, RESULTS_DIR_NAME}:
            continue
        shutil.move(str(item), str(results_dir / item.name))


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Scratch MVP for COMPSs Reproducibility Service")
    parser.add_argument("source", help="RO-Crate path, zip file, or URL")
    parser.add_argument(
        "--backend",
        choices=["auto", "local", "slurm"],
        default="auto",
        help="Runtime backend to use",
    )
    parser.add_argument(
        "--provenance",
        action="store_true",
        help="Pass --provenance to the COMPSs runtime command",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print the final command without running it",
    )
    parser.add_argument(
        "--extra-flag",
        action="append",
        default=[],
        help="Extra runtime flag to inject",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    base_dir = Path.cwd()
    workspace = create_workspace(base_dir)

    backend = detect_backend() if args.backend == "auto" else args.backend
    print(f"Selected backend: {backend}")

    crate_root = acquire_source(args.source, workspace.crate_root)
    print(f"Crate root: {crate_root}")

    before = {item.name for item in crate_root.iterdir()}
    command = build_command(
        crate_root=crate_root,
        backend=backend,
        provenance=args.provenance,
        extra_flags=args.extra_flag,
    )

    print("Final command:")
    print(" ".join(command))

    if args.dry_run:
        return 0

    return_code = run_command(command, cwd=crate_root, log_dir=workspace.log_dir)

    try:
        move_new_outputs(crate_root, workspace.results_dir, before)
    except Exception as exc:
        print(f"Warning: could not move outputs into Results/: {exc}", file=sys.stderr)

    print(f"Results directory: {workspace.results_dir}")
    return return_code


if __name__ == "__main__":
    raise SystemExit(main())