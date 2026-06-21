FROM python:3.14

ENV PYTHONUNBUFFERED=1

# Install uv
# Ref: https://docs.astral.sh/uv/guides/integration/docker/#installing-uv
COPY --from=ghcr.io/astral-sh/uv:0.9.26 /uv /uvx /bin/

# Compile bytecode
# Ref: https://docs.astral.sh/uv/guides/integration/docker/#compiling-bytecode
ENV UV_COMPILE_BYTECODE=1

# uv Cache
# Ref: https://docs.astral.sh/uv/guides/integration/docker/#caching
ENV UV_LINK_MODE=copy

WORKDIR /app/

# Place executables in the environment at the front of the path
# Ref: https://docs.astral.sh/uv/guides/integration/docker/#using-the-environment
ENV PATH="/app/.venv/bin:$PATH"

# Install dependencies
# Ref: https://docs.astral.sh/uv/guides/integration/docker/#intermediate-layers
RUN --mount=type=cache,target=/root/.cache/uv \
    --mount=type=bind,source=uv.lock,target=uv.lock \
    --mount=type=bind,source=pyproject.toml,target=pyproject.toml \
    uv sync --frozen --no-install-workspace --extra ml --extra redis --package app

COPY ./backend/scripts /app/backend/scripts

COPY ./backend/pyproject.toml ./backend/alembic.ini /app/backend/

COPY ./backend/app /app/backend/app

# Sync the project
# Ref: https://docs.astral.sh/uv/guides/integration/docker/#intermediate-layers
RUN --mount=type=cache,target=/root/.cache/uv \
    --mount=type=bind,source=uv.lock,target=uv.lock \
    --mount=type=bind,source=pyproject.toml,target=pyproject.toml \
    uv sync --frozen --extra ml --extra redis --package app

# The vendored Uni-Sign model code (models.py) imports torchvision, which is not
# part of the locked `ml` extra. Install it pinned to the resolved torch so the
# wheel matches (avoids torch being upgraded/downgraded).
RUN --mount=type=cache,target=/root/.cache/uv \
    uv pip install "torchvision" "torch==2.10.0"

# Run the app as a non-root user. The build steps above need root (uv install
# and bytecode compilation); only the final runtime process drops privileges,
# which limits the blast radius of a container compromise.
#
# ML caches (Hugging Face, Torch) and the model directory are relocated under
# the user's home so the named volumes mounted there (see compose.yml) are
# owned by — and writable for — the non-root user.
RUN useradd --create-home appuser \
    && mkdir -p /home/appuser/.cache/huggingface \
                /home/appuser/.cache/torch \
                /home/appuser/.signspeak/models \
                /app/backend/models \
    && chown -R appuser:appuser /home/appuser /app/backend/models

WORKDIR /app/backend/

USER appuser

CMD ["fastapi", "run", "--workers", "1", "app/main.py"]
