FROM python:3.12-slim

WORKDIR /app

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

RUN apt-get update -qq \
    && apt-get install -y -qq --no-install-recommends ca-certificates rclone \
    && rm -rf /var/lib/apt/lists/*

COPY pyproject.toml ./
COPY src/sts/__init__.py ./src/sts/__init__.py
RUN pip install --no-cache-dir .

COPY src ./src
RUN pip install --no-cache-dir --no-deps .

COPY scripts ./scripts
COPY configs ./configs

CMD ["python", "scripts/run_swing_forward_daily.py", "--help"]
