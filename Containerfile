FROM python:3.12-slim

# System dependencies. D-53: no OpenCode here — nothing in this container
# calls an LLM anymore (that happens on the host via scripts/llm-call.sh
# before the container ever starts); this image runs pytest/smoke_check
# against untrusted generated code only, hence --network none in
# sandbox-run.sh and no curl/agent-runtime install here either.
RUN apt-get update && apt-get install -y --no-install-recommends \
    git ca-certificates tar \
    && rm -rf /var/lib/apt/lists/*

# Pytest toolchain + app deps (always installed). D-204: exact pins — these
# tools decide gate behavior (pytest + json-report shape the verdict, ruff and
# mypy shape the lint/type gates), so a rebuild must not change them silently.
# Versions are what the image resolved on 2026-10-01; bump deliberately.
RUN pip install --no-cache-dir \
    pytest==8.4.2 pytest-json-report==1.5.0 pytest-asyncio==0.26.0 \
    pytest-cov==7.1.0 ruff==0.16.4 mypy==2.3.1 respx==0.23.1 \
    fastapi==0.141.1 uvicorn==0.52.4 httpx==0.28.1 pydantic==2.13.4

# Browser oracle (D-58): chromium + playwright baked at BUILD time — the
# sandbox runs --network none, so nothing can be fetched at test time.
# Spike-proven on aarch64 (2026-07-07): green inside the full sandbox
# contract, +1.2 GB accepted (constraint 4; no second "light" image).
# Shared browsers path: HOME is tmpfs in the sandbox, so the default
# ~/.cache location would vanish — install to a fixed root-owned path.
RUN pip install --no-cache-dir playwright==1.62.0 pytest-playwright==0.9.0 && \
    PLAYWRIGHT_BROWSERS_PATH=/ms-playwright playwright install --with-deps chromium
ENV PLAYWRIGHT_BROWSERS_PATH=/ms-playwright

# Project deps. Copy ONLY the dependency manifest: COPY . would retain source,
# local env files, pipeline state, and captures in an earlier image layer even
# if a later RUN removed the directory. Child projects using another stack
# adapt this project-owned Containerfile under BLUEPRINT.md Rule 3.
COPY requirements.txt /tmp/requirements.txt
RUN pip install --no-cache-dir -r /tmp/requirements.txt && \
    rm -f /tmp/requirements.txt

# Non-root user
RUN useradd -m -u 1000 agent
USER agent
WORKDIR /work
