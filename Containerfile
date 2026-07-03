FROM python:3.12-slim

# System dependencies. D-53: no OpenCode here — nothing in this container
# calls an LLM anymore (that happens on the host via scripts/llm-call.sh
# before the container ever starts); this image runs pytest/smoke_check
# against untrusted generated code only, hence --network none in
# sandbox-run.sh and no curl/agent-runtime install here either.
RUN apt-get update && apt-get install -y --no-install-recommends \
    git ca-certificates tar \
    && rm -rf /var/lib/apt/lists/*

# Pytest toolchain + app deps (always installed)
RUN pip install --no-cache-dir \
    pytest pytest-json-report pytest-asyncio pytest-cov ruff mypy respx \
    fastapi uvicorn httpx pydantic

# Project deps — only if requirements.txt exists at build time.
# Rebuild image after bootstrap.sh generates it (see BLUEPRINT.md Rule 3).
COPY . /tmp/ctx
RUN if [ -f /tmp/ctx/requirements.txt ]; then \
      pip install --no-cache-dir -r /tmp/ctx/requirements.txt; \
    fi && rm -rf /tmp/ctx

# Non-root user
RUN useradd -m -u 1000 agent
USER agent
WORKDIR /work
