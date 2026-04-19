# Office Docs to MD Sync

Local web app for Windows and Linux that watches folders, converts Office documents to Markdown, stores them inside a target workspace subdirectory, and optionally tracks the generated Markdown in Git.

## Features

- Multiple sync tasks managed from a local web UI
- Office conversion via `markitdown`
- Direct Markdown output for text files such as `txt`, `md`, `csv`, `tsv`, and custom extensions
- Full mirror behavior for deletes and renames
- Optional Git init, commit, and delayed push per task
- SQLite-backed config and event history
- Windows service and systemd install scripts

## Quick start

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e .[dev]
python3 run.py
```

Open `http://127.0.0.1:8080`.

## Git behavior

- Set the task `target_root` as the repository root and output workspace.
- Set `output_subdir` to choose where generated Markdown lives under the target root.
- Auto push uses the system git credential or SSH setup already present on the machine.

## Service install

Linux:

```bash
./scripts/install-systemd.sh /path/to/project office-docs-to-md-sync
```

Windows PowerShell:

```powershell
.\scripts\install-windows-service.ps1 -AppDir C:\path\to\project
```

## Test

```bash
pytest
```
