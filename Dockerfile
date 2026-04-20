FROM python:3.12-alpine AS builder

ENV PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

RUN apk add --no-cache build-base git libffi-dev

WORKDIR /src

COPY pyproject.toml README.md ./
COPY run_app.py ./
COPY app ./app
COPY markitdown ./markitdown
COPY office-docs-to-md-sync.spec ./

RUN python -m pip install --upgrade pip \
    && python -m pip install --no-cache-dir . pyinstaller \
    && pyinstaller --noconfirm office-docs-to-md-sync.spec


FROM alpine:3.22

ENV HOST=0.0.0.0 \
    PORT=8080 \
    APP_DATA_DIR=/data

RUN apk add --no-cache git libgcc libstdc++

WORKDIR /app

COPY --from=builder /src/dist/office-docs-to-md-sync /app/office-docs-to-md-sync

RUN ln -s /app/office-docs-to-md-sync/office-docs-to-md-sync /usr/local/bin/office-docs-to-md-sync

EXPOSE 8080

VOLUME ["/data"]

CMD ["office-docs-to-md-sync"]
