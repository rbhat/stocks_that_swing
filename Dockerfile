FROM python:3.12-slim

WORKDIR /app

# rclone is invoked by sts.forward.sync via subprocess; curl only for the install step.
RUN apt-get update -qq \
    && apt-get install -y -qq --no-install-recommends curl unzip ca-certificates \
    && curl -fsSL https://rclone.org/install.sh | bash \
    && apt-get purge -y -qq curl unzip \
    && apt-get autoremove -y -qq \
    && rm -rf /var/lib/apt/lists/*

# Third-party deps first, keyed on pyproject.toml alone (parent pattern):
# editing src/ doesn't bust this layer.
COPY pyproject.toml ./
COPY src/sts/__init__.py ./src/sts/__init__.py
RUN --mount=type=cache,target=/root/.cache/pip pip install .

COPY src ./src
RUN --mount=type=cache,target=/root/.cache/pip pip install --no-deps .

COPY scripts ./scripts
COPY configs ./configs
COPY universe.yaml ./

# Jobs read .env from CWD (sts.env.load default "./.env" — bind-mounted),
# write ledger/, cache/, logs/ — all bind mounts; container runs as the
# host user (compose `user:`), so no useradd needed here.
CMD ["python", "scripts/forward_eod.py", "--help"]
