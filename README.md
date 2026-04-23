# Office Docs to MD Sync

[![CI](https://github.com/flier268/office-docs-to-md-sync/actions/workflows/ci.yml/badge.svg)](https://github.com/flier268/office-docs-to-md-sync/actions/workflows/ci.yml)
[![Version](https://img.shields.io/badge/version-0.1.0-blue.svg)](https://github.com/flier268/office-docs-to-md-sync/releases)
[![Image](https://img.shields.io/badge/image-ghcr.io%2Fflier268%2Foffice--docs--to--md--sync-2496ed.svg)](https://github.com/flier268/office-docs-to-md-sync/pkgs/container/office-docs-to-md-sync)

Local web app for Windows and Linux that watches folders, converts Office documents to Markdown, stores them inside a target workspace subdirectory, and optionally tracks the generated Markdown in Git.

Latest container image: `ghcr.io/flier268/office-docs-to-md-sync:latest`

## Features

- Multiple sync tasks managed from a local web UI
- Office conversion via `markitdown`
- Direct Markdown output for text files such as `txt`, `md`, `csv`, `tsv`, and custom extensions
- Full mirror behavior for deletes and renames
- File event watching with periodic hash-based scans to catch missed changes
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
- Each target repo keeps `.office-docs-sync-state.json` at the repo root with per-task source file hashes and output mappings.
- The app still uses filesystem events for low-latency sync, but every task also runs a periodic hash scan to catch missed updates and deletes.
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

- Pushing a tag like `v0.1.0` runs `.github/workflows/release.yml` and publishes both the PyInstaller Linux bundle and Windows bundle to GitHub Releases.
- You can also run the same workflow manually from the GitHub Actions UI by selecting a branch, then providing a full `v*` tag such as `v0.1.0`. The workflow creates and pushes that tag from the selected branch before publishing the release, and it fails if that release tag already exists unless you explicitly enable `allow_move_release_tag`.
- Manual runs now treat the release tag and `latest` separately. Set `mark_as_latest` only when that release should become the current latest release.
- Set `allow_move_release_tag` only when you intentionally want to force-move an existing `v*` release tag to the selected commit.
- When a release is marked as latest, the workflow force-moves the Git tag `latest` to that release commit and also publishes the container `latest` tag.
- The same workflow always publishes multi-arch Docker images to `ghcr.io/<owner>/<repo>` with tags `vX.Y.Z` and `X.Y.Z`, and only publishes `latest` when that release is marked as latest.
- If the release for that tag already exists, the workflow updates the release and replaces old assets. Re-pushing the same image tag to GHCR also replaces the previous image manifest for that tag.
- `.github/workflows/monthly-image.yml` also publishes the container image automatically at `00:00 UTC` on the first day of every month from the Git tag `latest`, tagging it as `edge` and `monthly-YYYY-MM`.
- You can run the monthly image workflow manually from the GitHub Actions UI if you want to refresh the container image outside the normal schedule.

## Continuous integration

- Pushing commits or opening a pull request runs `.github/workflows/ci.yml`.
- The CI workflow installs the project with `.[dev]` extras on Python 3.12 and runs `pytest`.
