FROM python:3.12-alpine AS builder

ENV PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

RUN apk add --no-cache build-base git libffi-dev

WORKDIR /src

COPY pyproject.toml README.md ./
COPY app ./app

RUN python -m pip install --upgrade pip build \
    && python -m build \
    && mkdir -p /wheels \
    && python -m pip wheel --no-cache-dir --wheel-dir /wheels /src/dist/*.whl


FROM python:3.12-alpine

ENV PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    HOST=0.0.0.0 \
    PORT=8080 \
    APP_DATA_DIR=/data

RUN apk add --no-cache git libstdc++

WORKDIR /app

COPY --from=builder /wheels /wheels

RUN python -m pip install --no-cache-dir --no-index --find-links=/wheels /wheels/office_docs_to_md_sync-*.whl \
    && rm -rf /wheels

EXPOSE 8080

VOLUME ["/data"]

CMD ["office-docs-to-md-sync"]
