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
office-docs-to-md-sync
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

## Build binary

```bash
python -m pip install pyinstaller
pyinstaller --noconfirm office-docs-to-md-sync.spec
```

The generated binary bundle is written to `dist/office-docs-to-md-sync/` and includes the web UI static assets.
The packaged dependency set is intentionally limited to the `markitdown` extras this app targets: `docx`, `pptx`, `xlsx`, and `pdf`.

## Docker

```bash
docker build -t office-docs-to-md-sync .
docker run --rm -p 8080:8080 -v "$(pwd)/.localdata:/data" office-docs-to-md-sync
```

### Docker Compose

```bash
cp docker-compose.example.yml docker-compose.yml
docker compose up -d
```

The included example mounts `./data` to `/data` for the app database and runtime state.

## GitHub release

- Pushing a tag like `v0.1.0` runs `.github/workflows/release.yml` and publishes the PyInstaller Linux bundle to GitHub Releases.
- You can also run the same workflow manually from the GitHub Actions UI by selecting a branch, then providing a full `v*` tag such as `v0.1.0`. If the tag does not exist yet, the workflow creates and pushes it from the selected branch before publishing the release.
- The same workflow also publishes Docker images to `ghcr.io/<owner>/<repo>` with tags `vX.Y.Z`, `X.Y.Z`, and `latest`.
- If the release for that tag already exists, the workflow updates the release and replaces old assets. Re-pushing the same image tag to GHCR also replaces the previous image manifest for that tag.
