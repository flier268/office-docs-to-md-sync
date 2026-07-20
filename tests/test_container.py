from pathlib import Path


def test_container_runs_as_unprivileged_user() -> None:
    dockerfile = Path("Dockerfile").read_text(encoding="utf-8")

    assert "adduser -S -D -h /home/app -u 1000 -G app app" in dockerfile
    assert "USER app:app" in dockerfile
    assert "COPY --chown=app:app" not in dockerfile
    assert dockerfile.index("USER app:app") < dockerfile.index('CMD ["office-docs-to-md-sync"]')


def test_compose_uses_local_data_mount() -> None:
    compose = Path("docker-compose.example.yml").read_text(encoding="utf-8")

    assert "./data:/data" in compose


def test_compose_defaults_to_unprivileged_user_with_override() -> None:
    compose = Path("docker-compose.example.yml").read_text(encoding="utf-8")

    assert 'user: "${APP_UID:-1000}:${APP_GID:-1000}"' in compose
