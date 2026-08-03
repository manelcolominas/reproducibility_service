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
RESULTS_DIR_NAME = "Results"
LOG_DIR_NAME = "log"
CRATE_METADATA_FILE = "ro-crate-metadata.json"
SUBMISSION_FILE = "compss_submission_command_line.txt"
VALID_EXECUTABLES = ("runcompss", "enqueue_compss")


@dataclass(frozen=True)
class RunPaths:
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
    except FileNotFoundError:
        return "local"
    except Exception:
        return "local"


def download_to(url: str, destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    urllib.request.urlretrieve(url, destination)


def source_kind(raw: str) -> str:
    if raw.startswith(("http://", "https://")):
        return "url"
    if zipfile.is_zipfile(raw):
        return "zip"
    if Path(raw).is_dir():
        return "directory"
    return "path"


def acquire_source(raw_source: str, work_root: Path) -> Path:
    kind = source_kind(raw_source)
    crate_root = work_root / "crate"
    crate_root.mkdir(parents=True, exist_ok=True)

    if kind == "url":
        archive = work_root / "source.zip"
        download_to(raw_source, archive)
        return extract_archive(archive, crate_root)
    if kind == "zip":
        return extract_archive(Path(raw_source), crate_root)
    if kind == "directory":
        copytree(Path(raw_source), crate_root)
        return normalize_crate_root(crate_root)
    if kind == "path" and Path(raw_source).exists():
        copytree(Path(raw_source), crate_root)
        return normalize_crate_root(crate_root)

    raise SystemExit(f"Unsupported source: {raw_source}")


def copytree(src: Path, dst: Path) -> None:
    if src.is_dir():
        for item in src.iterdir():
            target = dst / item.name
            if item.is_dir():
                target.mkdir(parents=True, exist_ok=True)
                copytree(item, target)
            else:
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(item, target)
    else:
        dst.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dst / src.name)


def extract_archive(archive: Path, extract_root: Path) -> Path:
    with zipfile.ZipFile(archive, "r") as zip_ref:
        zip_ref.extractall(extract_root)
    return normalize_crate_root(extract_root)


def normalize_crate_root(root: Path) -> Path:
    if (root / CRATE_METADATA_FILE).exists() or (root / SUBMISSION_FILE).exists():
        return root

    candidates = list(root.rglob(CRATE_METADATA_FILE))
    if candidates:
        return candidates[0].parent

    candidates = list(root.rglob(SUBMISSION_FILE))
    if candidates:
        return candidates[0].parent

    raise SystemExit(
        f"Could not locate a crate root under {root}. "
        f"Expected {CRATE_METADATA_FILE} or {SUBMISSION_FILE}."
    )


def walk_strings(node: object) -> Iterable[str]:
    if isinstance(node, dict):
        for key, value in node.items():
            if key == "description" and isinstance(value, str):
                yield value
            yield from walk_strings(value)
    elif isinstance(node, list):
        for item in node:
            yield from walk_strings(item)
    elif isinstance(node, str):
        yield node


def discover_command(crate_root: Path) -> list[str]:
    command_file = crate_root / SUBMISSION_FILE
    if command_file.exists():
        content = command_file.read_text(encoding="utf-8").strip()
        if content:
            return shlex.split(content)

    metadata_file = crate_root / CRATE_METADATA_FILE
    if metadata_file.exists():
        try:
            doc = json.loads(metadata_file.read_text(encoding="utf-8"))
            for candidate in walk_strings(doc):
                if candidate.startswith(VALID_EXECUTABLES):
                    return shlex.split(candidate)
        except Exception as exc:
            raise SystemExit(f"Could not parse {metadata_file}: {exc}") from exc

    raise SystemExit(
        f"Could not discover a COMPSs submission command in {crate_root}. "
        f"Expected {SUBMISSION_FILE} or a runnable description in {CRATE_METADATA_FILE}."
    )


def backend_executable(backend: str) -> str:
    return "enqueue_compss" if backend == "slurm" else "runcompss"


def build_command(
    crate_root: Path,
    backend: str,
    provenance: bool,
    extra_flags: list[str],
) -> list[str]:
    command = discover_command(crate_root)
    if not command:
        raise SystemExit("Empty submission command")

    command[0] = backend_executable(backend)

    insertion_index = 1
    if provenance:
        command.insert(insertion_index, "--provenance")
        insertion_index += 1

    for flag in extra_flags:
        command.insert(insertion_index, flag)
        insertion_index += 1

    return command


def tee_stream(stream, log_file):
    for line in iter(stream.readline, ""):
        print(line, end="")
        log_file.write(line)
        log_file.flush()
    stream.close()


def run_command(command: list[str], cwd: Path, log_dir: Path) -> int:
    log_dir.mkdir(parents=True, exist_ok=True)
    stdout_path = log_dir / "out.log"
    stderr_path = log_dir / "err.log"

    print("Executing:", " ".join(command))
    print("Working directory:", cwd)

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

    with stdout_path.open("w", encoding="utf-8") as stdout_log, stderr_path.open(
        "w", encoding="utf-8"
    ) as stderr_log:
        stdout_thread = threading.Thread(target=tee_stream, args=(process.stdout, stdout_log))
        stderr_thread = threading.Thread(target=tee_stream, args=(process.stderr, stderr_log))
        stdout_thread.start()
        stderr_thread.start()
        process.wait()
        stdout_thread.join()
        stderr_thread.join()

    print("stdout log:", stdout_path)
    print("stderr log:", stderr_path)
    return process.returncode


def move_new_top_level_outputs(crate_root: Path, results_dir: Path, before: set[str]) -> None:
    results_dir.mkdir(parents=True, exist_ok=True)

    for item in crate_root.iterdir():
        if item.name in before:
            continue
        if item.name in {LOG_DIR_NAME, RESULTS_DIR_NAME}:
            continue
        shutil.move(str(item), str(results_dir / item.name))


def build_run_paths(base_dir: Path) -> RunPaths:
    root = base_dir / f"{RUN_PREFIX}{timestamp()}"
    crate_root = root / "crate"
    log_dir = root / LOG_DIR_NAME
    results_dir = root / RESULTS_DIR_NAME

    root.mkdir(parents=True, exist_ok=False)
    crate_root.mkdir(parents=True, exist_ok=True)
    log_dir.mkdir(parents=True, exist_ok=True)
    results_dir.mkdir(parents=True, exist_ok=True)

    return RunPaths(root=root, crate_root=crate_root, log_dir=log_dir, results_dir=results_dir)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Scratch MVP for COMPSs Reproducibility Service")
    parser.add_argument("source", help="RO-Crate path, zip file, or URL")
    parser.add_argument("--backend", choices=["auto", "local", "slurm"], default="auto")
    parser.add_argument("--provenance", action="store_true", help="Pass --provenance to runcompss/enqueue_compss")
    parser.add_argument("--dry-run", action="store_true", help="Print the command without executing it")
    parser.add_argument("--extra-flag", action="append", default=[], help="Extra runtime flag to inject")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    base_dir = Path.cwd()
    paths = build_run_paths(base_dir)

    backend = detect_backend() if args.backend == "auto" else args.backend
    print("Detected backend:", backend)

    crate_root = acquire_source(args.source, paths.crate_root)
    print("Crate root:", crate_root)

    command = build_command(
        crate_root=crate_root,
        backend=backend,
        provenance=args.provenance,
        extra_flags=args.extra_flag,
    )

    print("Final command:", " ".join(command))

    if args.dry_run:
        return 0

    before = {item.name for item in crate_root.iterdir()}
    return_code = run_command(command, cwd=crate_root, log_dir=paths.log_dir)

    try:
        move_new_top_level_outputs(crate_root, paths.results_dir, before)
    except Exception as exc:
        print(f"Warning: could not move outputs into Results/: {exc}", file=sys.stderr)

    print("Results directory:", paths.results_dir)
    return return_code


if __name__ == "__main__":
    raise SystemExit(main())