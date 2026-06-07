FROM python:3.12-slim

# System dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    git curl ca-certificates tar \
    && rm -rf /var/lib/apt/lists/*

# OpenCode (pinned to host version) — make globally available for `agent` user
RUN curl -fsSL https://opencode.ai/install | bash -s -- --version 1.15.13 \
    && cp /root/.opencode/bin/opencode /usr/local/bin/opencode

# Pytest toolchain (always installed)
RUN pip install --no-cache-dir \
    pytest pytest-json-report pytest-asyncio pytest-cov ruff mypy respx

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
