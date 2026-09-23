# juno, packaged. Build context is the project folder; secrets and data are mounted at run time.
FROM python:3.13-slim

ENV PYTHONUNBUFFERED=1 \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    ASSISTANT_HOME=/app \
    PYDANTIC_AI_NO_BANNER=1

COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/
WORKDIR /app

# dependencies first, so code changes don't reinstall them
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project

COPY src ./src
COPY persona.md assistant.yaml courses.yaml ./
RUN uv sync --frozen --no-dev

CMD ["uv", "run", "--no-sync", "assistant", "run"]
