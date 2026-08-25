# COMPSs Reproducibility Service

<p align="center">
  <img src="./APP-REQ/logo-color.svg" alt="Logo" width="220">
</p>

A CLI tool that reproduces a [COMPSs](https://compss-doc.readthedocs.io/) workflow run from an **RO-Crate**. Point it at a crate (a local directory, a `.zip` file, or a remote URL e.g. from WorkflowHub) — and it will import the crate, inspect its metadata, verify that the referenced input files are present, build the `compss` submission command, and execute it and (optionaly) record new provenance.

## Pre-requisites

- COMPSs must be installed on your local machine, or the COMPSs module must be loaded on the cluster. See the [COMPSs Official Installation Guide](https://compss-doc.readthedocs.io/en/stable/Sections/01_Installation.html).
- Python 3.11+ (the codebase uses modern typing syntax such as `X | None` and `slots=True` dataclasses).
- Python dependencies: `rich`, `questionary`, `ro-crate-py` (`rocrate`), `PyYAML`.
- Ensure that all dependencies for the experiment you wish to reproduce are satisfied on the machine where you want to resubmit the application.

## How to Use

Run the service with the path or URL to the RO-Crate as the first argument:

```bash
compss_reproducibility_service <link_or_path_to_crate> [options]
```

For example:

```bash
compss_reproducibility_service workflow-635-1.crate.zip \
  --backend slurm \
  --provenance \
  --participant-name "John Doe" \
  --participant-email "john.doe@example.com" \
  --participant-org "Example Org" \
  --participant-orcid "0000-0001-2345-6789" \
  --participant-ror "https://ror.org/123456789"
```

### CLI options

| Flag | | Description |
| --- | --- |--- |
| `source` |Mandatory| Local directory, `.zip` file, or URL of the RO-Crate |
| `--run-id` |Optional| Identifier for this run (default: timestamp, `YYYYMMDD_HHMMSS`) |
| `--backend {auto,local,slurm}` |Optional| Execution backend to use (default: `auto`) |
| `--command` |Optional| Override the COMPSs submission command discovered from the crate metadata |
| `--extra-flag` |Optional| Extra runtime flag to append to the submission command (repeatable) |
| `-p`, `--provenance` |Optional| Enable provenance and write `ro-crate-info.yaml` |
| `--participant-name` |Optional| Participant name to record in the generated provenance |
| `--participant-email` |Optional| Participant email |
| `--participant-org` |Optional| Participant organization |
| `--participant-orcid` |Optional| Participant ORCID |
| `--participant-ror` |Optional| Participant ROR |
| `-y`, `--yes` |Optional| Skip confirmation prompts (non-interactive mode) |

## What the Service Does

Each run walks through the same pipeline:

1. **Import** — the crate source is resolved (downloaded if it's a URL, extracted if it's a `.zip`, used in place if it's already a directory) and loaded as an RO-Crate.
2. **Inspect** — the crate's `ro-crate-metadata.json` is parsed into a structured summary: name, description, authors, license, main entity, prior execution details, and the original submission command line.
3. **Verify** — every input referenced in the metadata is checked against the filesystem (existence, size) and the results are shown in a status table.
4. **Plan** — a `runcompss`/`enqueue_compss` submission command is built for the selected backend (`local` or `slurm`), honoring `--command`, `--extra-flag`, and any interactive edits.
5. **Provenance** *(optional)* — if `-p/--provenance` is set, participant details are collected and `ro-crate-info.yaml` is written alongside the results.
6. **Execute** — the resolved command is submitted, and a final success/failure summary is printed and logged.

### Features

- **Interactive command editing**: review and edit the discovered submission command (add, remove, or change flag values) before it runs.
- **File verification**: input files are checked against the crate metadata (size, presence) and reported in a status table before execution.
- **Isolated run directory**: each run happens inside its own `Results` directory, so it never interferes with your current working directory.
- **Results & provenance**: outputs are written to `reproducibility_service_{run_id}/Results`; when provenance is enabled, the generated RO-Crate is written there too.
- **Logging**: each run logs to `reproducibility_service_{run_id}/log/rs_log.txt`.

## Project Structure

The service follows a hexagonal (ports & adapters) layout, keeping business rules independent of I/O and the CLI:

```
domain/
  models/        # Crate, execution, verification value objects (framework-free)
  errors.py      # ServiceError hierarchy (ValidationError, FileSystemError, ExecutionError, ...)
application/
  ports/         # Protocols the use cases depend on (file system, executor, metadata parser)
  use_cases/     # import_crate, inspect_crate, verify_inputs, build_execution_plan, prepare_provenance
infrastructure/
  adapters.py    # Concrete implementations: LocalFileSystem, subprocess execution, metadata parsing/normalization
config/
  settings.py    # AppSettings — workspace/log/results directory naming, default backend, filenames
presentation/
  cli/
    app.py       # Orchestration only: wires adapters into use cases and drives the pipeline
    view.py      # Rich/questionary rendering — no business logic
```

`app.py` never contains business logic itself — it only builds requests for the use cases in `application/use_cases`, and hands the results to `view.py` for rendering.

### Experiment Requirements

1. 
2. 
3. 
---

I hope you find this service helpful!