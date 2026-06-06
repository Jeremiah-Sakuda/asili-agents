# Asili Operations Team - Production Dockerfile
# Python runtime + Node.js, so the agents can spawn the MongoDB MCP server
# (`npx mongodb-mcp-server`) in-container.
FROM node:20-slim AS node

FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PORT=8080 \
    NPM_CONFIG_CACHE=/home/appuser/.npm

WORKDIR /app

# --- Node.js runtime (required for the MongoDB MCP server via npx) ---
COPY --from=node /usr/local/bin/node /usr/local/bin/node
COPY --from=node /usr/local/lib/node_modules /usr/local/lib/node_modules
RUN ln -sf /usr/local/lib/node_modules/npm/bin/npm-cli.js /usr/local/bin/npm \
    && ln -sf /usr/local/lib/node_modules/npm/bin/npx-cli.js /usr/local/bin/npx \
    && node --version && npm --version

# --- System dependencies ---
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    && rm -rf /var/lib/apt/lists/*

# --- Python dependencies ---
COPY pyproject.toml README.md ./
COPY src/ ./src/
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir .

# --- Pre-cache the MongoDB MCP server so the first agent call doesn't pay a
#     cold download (npx will use this global install). Non-fatal if it fails. ---
RUN npm install -g mongodb-mcp-server@latest \
    || echo "WARN: mongodb-mcp-server preinstall failed; npx will fetch it at runtime"

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
