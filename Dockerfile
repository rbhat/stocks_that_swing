# The dashboard SPA is built here rather than committed, so the image is the
# only place a bundle exists and `deploy.sh` can keep shipping plain sources.
FROM node:22-slim AS frontend

WORKDIR /build
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci
COPY frontend ./
RUN npm run build


FROM python:3.12-slim

WORKDIR /app

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

RUN apt-get update -qq \
    && apt-get install -y -qq --no-install-recommends ca-certificates rclone \
    && rm -rf /var/lib/apt/lists/*

COPY pyproject.toml ./
COPY src/sts/__init__.py ./src/sts/__init__.py
RUN pip install --no-cache-dir ".[dashboard]"

COPY src ./src
RUN pip install --no-cache-dir --no-deps .

COPY scripts ./scripts
COPY configs ./configs
COPY --from=frontend /build/dist ./frontend/dist

CMD ["python", "scripts/run_swing_forward_daily.py", "--help"]
