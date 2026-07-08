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

# Browser oracle (D-58): chromium + playwright baked at BUILD time — the
# sandbox runs --network none, so nothing can be fetched at test time.
# Spike-proven on aarch64 (2026-07-07): green inside the full sandbox
# contract, +1.2 GB accepted (constraint 4; no second "light" image).
# Shared browsers path: HOME is tmpfs in the sandbox, so the default
# ~/.cache location would vanish — install to a fixed root-owned path.
RUN pip install --no-cache-dir playwright pytest-playwright && \
    PLAYWRIGHT_BROWSERS_PATH=/ms-playwright playwright install --with-deps chromium
ENV PLAYWRIGHT_BROWSERS_PATH=/ms-playwright

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
