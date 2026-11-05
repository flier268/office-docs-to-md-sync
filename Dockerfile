FROM python:3.12-alpine AS builder

COPY --from=ghcr.io/astral-sh/uv:0.13.7 /uv /bin/uv

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PROJECT_ENVIRONMENT=/src/.venv \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PATH="/src/.venv/bin:$PATH"

RUN apk add --no-cache build-base git libffi-dev binutils

WORKDIR /src

COPY pyproject.toml uv.lock README.md ./
COPY run_app.py ./
COPY app ./app
COPY office-docs-to-md-sync.spec ./

RUN uv sync --frozen --no-dev --group build \
    && python -c "import app.converter, markitdown" \
    && pyinstaller --noconfirm office-docs-to-md-sync.spec


FROM alpine:3.22

ENV HOST=0.0.0.0 \
    PORT=8080 \
    APP_DATA_DIR=/data \
    HOME=/home/app

RUN apk add --no-cache git libgcc libstdc++ \
    && addgroup -S -g 1000 app \
    && adduser -S -D -h /home/app -u 1000 -G app app \
    && mkdir -p /data /home/app \
    && chown app:app /data /home/app

WORKDIR /app

COPY --from=builder /src/dist/office-docs-to-md-sync /app/office-docs-to-md-sync

RUN ln -s /app/office-docs-to-md-sync/office-docs-to-md-sync /usr/local/bin/office-docs-to-md-sync

EXPOSE 8080

VOLUME ["/data"]

USER app:app

CMD ["office-docs-to-md-sync"]
