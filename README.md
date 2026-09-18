# COMPSs Reproducibility Service

<p align="center">
  <img src="logo-color.svg" alt="Logo" width="220">
</p>

A CLI tool that reproduces a [COMPSs](https://compss-doc.readthedocs.io/) workflow run from an **RO-Crate**. Point it at a crate (a local directory, a `.zip` file, or a remote URL e.g. from WorkflowHub) — and it will import the crate, inspect its metadata, verify that the referenced input files are present, build the `compss` submission command, and execute it and (optionaly) record new provenance.

## Pre-requisites

- COMPSs must be installed on your local machine, or the COMPSs module must be loaded on the cluster. See the [COMPSs Official Installation Guide](https://compss-doc.readthedocs.io/en/stable/Sections/01_Installation.html).
- Python dependencies: `rich`, `questionary`, `rocrate`, `PyYAML`.
- Ensure that all dependencies for the experiment you wish to reproduce are satisfied on the machine where you want to resubmit the application.

## How to Use

Run the service with the path or URL to the RO-Crate as the first argument:

```bash
compss_reproducibility_service <url_or_path_to_crate> [options]
```

`The path to the RO-Crate can be an absolute or a relative path`

For example:

```bash
compss_reproducibility_service workflow-635-1.crate.zip \
or 
compss_reproducibility_service https://workflowhub.org/workflows/635/ro_crate?version=1\
  --run_id=365 \
  --backend=slurm \
  --provenance \
  --agent_name="John Doe" \
  or
  --agent_name "John Doe" \
  --agent_email=john.doe@example.com \
  --agent_org="Barcelona Supercomputing Center" \
  --agent_orcid=https://0000-0001-2345-6789 \
  --agent_ror=https://ror.org/123456789 \
  --extra_flag=--lang=python \
  --extra_flag=--workers=4 \
  --data_persistence \
  --command="runcompss/enqueue_compss main.py --log_level=info --lang=python --provenance"
```

### CLI options

| Flag                           | | Description |
|--------------------------------| --- |--- |
| `source`                       |Mandatory| Local directory, `.zip` file, or URL of the RO-Crate |
| `--run_id`                     |Optional| Identifier for this run (default: timestamp, `YYYYMMDD_HHMMSS`) |
| `--backend {auto,local,slurm}` |Optional| Execution backend to use (default: `auto`) |
| `--command`                    |Optional| Override the COMPSs submission command discovered from the crate metadata |
| `--extra-flag`                 |Optional| Extra runtime flag to append to the submission command (repeatable) |
| `-p`, `--provenance`           |Optional| Enable provenance |
| `--agent_name`                 |Optional| Participant name to record in the generated provenance |
| `--agent_email`                |Optional| Participant email |
| `--agent_org`                  |Optional| Participant organization |
| `--agent_orcid`                |Optional| Participant ORCID |
| `--agent_ror`                  |Optional| Participant ROR |
| `-y`, `--yes`                  |Optional| Skip confirmation prompts (non-interactive mode) |
| `-data_persistence`            |Optional| Enables the data_persistence|


## Environment Variables

The service can read additional COMPSs flags from environment variables named
`COMPSS_RS_`. Environment-variable flags are applied after the flags from
the original submission command, so a matching environment-variable flag
overrides the original value.

```bash
export COMPSS_RS_1="--lang=python"
export COMPSS_RS_LOG_LEVEL="--log_level=info"
export COMPSS_RS_3="--workers=4"
export COMPSS_RS_PYTHONPATH="--pythonpath"

Command-line flags supplied with `--extra_flag` and environment variables are
combined before the execution plan is built.
```

### Behavior of some flags

- **`-p`, `--provenance`**:
  Enables provenance tracking for this run. When set, the service asks
  additional questions (agent name, data persistence) and writes an
  `ro-crate-info.yaml` describing the reproduction.

- **`-y`, `--yes`**:
  Skips confirmation prompts by auto-answering every yes/no question
  (the questions are still printed to the screen, together with the
  answer that was assumed). With `-y`, the following answers are used:
  - `Do you want to enable provenance for this reproduction? [y/N]: y`
  - `Do you want to provide your name? [y/N]: n` (the crate author is
    used instead, unless `--agent_name` is also provided)
  - `Do you want to enable data persistence? [y/N]: y`

  Note that `-y` also enables provenance by itself, so passing `-y`
  alone is equivalent to passing `-y --provenance`.

- **`--data_persistence`**:
  Enables data persistence for the provenance generation, regardless of
  whether `-y` is used.

- **`--agent_name`**:
  Sets the name of the agent recorded as the author of this reproduction
  run. If omitted and `-y` is used, the crate's original author is set as the agent of the reproduction.


### `--extra_flag` and Environment Variables

Both mechanisms let you add or override COMPSs runtime flags on top of the
submission command discovered from the crate, without editing the crate
itself.

- **`--extra_flag`** (repeatable): pass one flag per occurrence, (`--extra_flag=--lang=python`). Each one becomes an "ADD/override" edit
  applied to the discovered submission command.

- **Environment variables**: any variable named `COMPSS_RS_<suffix>` (e.g.
  `COMPSS_RS_1`, `COMPSS_RS_LOG_LEVEL`) is picked up automatically and its
  *value* is treated the same way as an `--extra_flag` value (e.g.
  `export COMPSS_RS_LOG_LEVEL="--log_level=info"`). Variables are sorted by
  name before being applied. If any `COMPSS_RS_*`  environment variables are found, the service always asks **"Do you want to use the environment variables?"**
  — this confirmation is shown even in non-interactive (`-y`) runs, so make
  sure to unset any `COMPSS_RS_*` variables you don't want to be prompted
  about when automating runs.

#### How they interact with each other and with the original command

Flags are merged in this order, and **later sources override earlier ones
when they target the same flag name**:

1. The submission command discovered from the crate metadata (or the one
   given via `--command`).
2. `--extra_flag` values (in the order given on the command line).
3. Selected environment-variable flags (`COMPSS_RS_*`).
4. Manual edits made through the interactive "modify submission command"
   step, if used.

In practice this means:
- An environment variable flag **overrides** the same flag coming from
  `--extra_flag` or from the original crate command.
- A flag added interactively while editing the command **overrides**
  both `--extra_flag` and environment-variable values.
- If a flag is not overridden by any of these sources, the original value
  from the crate's submission command is kept.


---

## What the Service Does

Each run walks through the same pipeline:

1. **Import** — the crate source is resolved (downloaded if it's a URL, extracted if it's a `.zip`, used in place if it's already a directory) and loaded as an RO-Crate.
2. **Inspect** — the crate's `ro-crate-metadata.json` is parsed into a structured summary: name, description authors, license, main entity, prior execution details, and the original submission command line.

3. **Verify** — check the files referenced by the crate metadata.

4. **Collect environment flags** — discover variables matching
   `COMPSS_RS_<number>`, sort them numerically, and optionally add their values
   to the submission command.

5. **Plan** — build the backend-specific COMPSs command, apply command-line and
   environment flags, remap crate paths, and remove unsupported flags.

6. **Provenance** *(optional)* — prepare `ro-crate-info.yaml`.

7. **Execute** — submit the final command and stream its output.

### Features

- **Interactive command editing**: review and edit the discovered submission command (add, remove, or change flag values) before it runs.
- **File verification**: input files are checked against the crate metadata (size, presence) and reported in a status table before execution.
- **Isolated run directory**: each run happens inside its own `Results` directory, so it never interferes with your current working directory.
- **Results & provenance**: outputs are written to `reproducibility_service_{run_id}/Results`; when provenance is enabled, the generated RO-Crate is written there too.
- **Logging**: each run logs to `reproducibility_service_{run_id}/log/rs_log.txt`.

---

### Experiment Requirements

For the crate to be importable and pass verification, it must satisfy:

1. **A valid `ro-crate-metadata.json` at the crate root.** This file is required to load the crate at all — if it's missing or malformed, the import step fails immediately.

2. **The crate's file layout must match what `ro-crate-metadata.json` declares.** Every entity listed under `hasPart` is checked against the filesystem, relative to the crate root:

   - **Input/output data files** — any entity whose `@id` starts with `dataset/`, `datasets/`, or `data/` must exist at that exact relative path (e.g. an entry `dataset/data/file0.txt` requires `<crate_root>/dataset/data/file0.txt` to exist).

   - **Software source code** — any entity of type `SoftwareSourceCode` must exist at its declared `@id` path (e.g. `application_sources/main.py`).

   Missing or size-mismatched files for these two categories are reported as verification **failures**; other missing entities (logs, README, config YAML, etc.) are only reported as **warnings**. Declared file sizes (`contentSize`) are also checked against the actual size on disk when present.

---

I hope you find this service helpful !