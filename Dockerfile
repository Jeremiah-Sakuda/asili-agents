# Asili Operations Team - Production Dockerfile
# Python runtime + Node.js, so the agents can spawn the MongoDB MCP server
# (`npx mongodb-mcp-server`) in-container.
FROM node:20-slim AS node

FROM python:3.11-slim

# MCP_SERVER_COMMAND points the app at the version-pinned binary baked below, so
# the agents never resolve/download mongodb-mcp-server from npm at runtime.
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PORT=8080 \
    NPM_CONFIG_CACHE=/home/appuser/.npm \
    MCP_SERVER_COMMAND=/usr/local/bin/mongodb-mcp-server

WORKDIR /app

# --- Node.js runtime (required for the MongoDB MCP server via npx) ---
COPY --from=node /usr/local/bin/node /usr/local/bin/node
COPY --from=node /usr/local/lib/node_modules /usr/local/lib/node_modules
RUN ln -sf /usr/local/lib/node_modules/npm/bin/npm-cli.js /usr/local/bin/npm \
    && ln -sf /usr/local/lib/node_modules/npm/bin/npx-cli.js /usr/local/bin/npx \
    && node --version && npm --version

# --- Python dependencies ---
# gcc is installed only to build any wheels lacking a prebuilt manylinux build,
# then purged in the SAME layer so the build toolchain never ships in the
# runtime image (smaller attack surface, nothing for an attacker to compile with).
COPY pyproject.toml README.md ./
COPY src/ ./src/
RUN apt-get update \
    && apt-get install -y --no-install-recommends gcc \
    && pip install --no-cache-dir --upgrade pip \
    && pip install --no-cache-dir . \
    && apt-get purge -y --auto-remove gcc \
    && rm -rf /var/lib/apt/lists/*

# --- Bake the MongoDB MCP server at an EXACT pinned version (supply-chain
#     hardening). Installed globally as root so the binary lands on /usr/local/bin
#     (world-executable, used directly via MCP_SERVER_COMMAND). FATAL on failure:
#     we never want the image to ship and then fetch an unpinned package from the
#     public registry at runtime while holding the Atlas connection string. ---
RUN npm install -g mongodb-mcp-server@1.12.0 \
    && test -x /usr/local/bin/mongodb-mcp-server

# --- Non-root user ---
RUN useradd --create-home --shell /bin/bash appuser \
    && mkdir -p /home/appuser/.npm \
    && chown -R appuser:appuser /home/appuser
USER appuser

EXPOSE 8080

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
    CMD python -c "import httpx; httpx.get('http://localhost:8080/')" || exit 1

# Run the application
CMD ["uvicorn", "asili_agents.api.main:app", "--host", "0.0.0.0", "--port", "8080"]
