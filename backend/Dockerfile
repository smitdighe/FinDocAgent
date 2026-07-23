# CPU-only runtime image (Render web service). torch resolves to CPU wheels on
# linux via the pytorch-cpu index pinned in pyproject/uv.lock. Chromium is
# included so one-off ingestion jobs can run in this image; the API itself
# never renders or batch-embeds.
FROM python:3.12-slim-bookworm

ENV PYTHONUNBUFFERED=1 \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    PLAYWRIGHT_BROWSERS_PATH=/ms-playwright

COPY --from=ghcr.io/astral-sh/uv:0.11 /uv /uvx /bin/

WORKDIR /app

# Dependency layer (cached until the lockfile changes).
COPY pyproject.toml uv.lock README.md ./
RUN uv sync --frozen --no-install-project --no-dev

COPY . .
RUN uv sync --frozen --no-dev
RUN uv run playwright install --with-deps chromium

ENV PATH="/app/.venv/bin:$PATH"
EXPOSE 8000

# Migrations run on deploy, then the API starts.
CMD ["sh", "-c", "alembic upgrade head && uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000}"]
