# =============================================================================
# Second Brain - Multi-stage Dockerfile
# =============================================================================
# Stage 1: Builder - install dependencies and build wheel
# Stage 2: Runtime - minimal image with only production dependencies
# =============================================================================

# -----------------------------------------------------------------------------
# Stage 1: Builder
# -----------------------------------------------------------------------------
FROM python:3.12-slim AS builder

# Set build-time environment variables
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /build

# Install build dependencies (minimal)
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    && rm -rf /var/lib/apt/lists/*

# Create virtual environment
RUN python -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

# Install dependencies first (for better layer caching)
COPY pyproject.toml ./
# Create minimal package for dependency resolution
RUN mkdir -p src/assistant && \
    echo "\"\"\"Second Brain package.\"\"\"" > src/assistant/__init__.py && \
    pip install --no-cache-dir .

# Copy source and reinstall to get the actual package
COPY src/ ./src/
RUN pip install --no-cache-dir .


# -----------------------------------------------------------------------------
# Stage 2: Runtime
# -----------------------------------------------------------------------------
FROM python:3.12-slim AS runtime

# Runtime environment variables
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    # App-specific paths
    SECOND_BRAIN_HOME=/var/lib/second-brain \
    # Timezone (can be overridden)
    TZ=UTC

WORKDIR /app

# Create non-root user for security
RUN groupadd --gid 1000 secondbrain && \
    useradd --uid 1000 --gid secondbrain --shell /bin/bash --create-home secondbrain && \
    mkdir -p /var/lib/second-brain/tokens \
             /var/lib/second-brain/cache \
             /var/lib/second-brain/logs \
             /var/lib/second-brain/queue && \
    chown -R secondbrain:secondbrain /var/lib/second-brain

# Copy virtual environment from builder
COPY --from=builder /opt/venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

# Copy application source (in case it's needed for debugging)
COPY --chown=secondbrain:secondbrain src/ ./src/

# Switch to non-root user
USER secondbrain

# Health check - verifies the assistant CLI is working
HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
    CMD python -m assistant check || exit 1

# Default command: run the Telegram bot
CMD ["python", "-m", "assistant", "run"]

# Labels for container metadata
LABEL org.opencontainers.image.title="Second Brain" \
      org.opencontainers.image.description="Personal AI Assistant" \
      org.opencontainers.image.source="https://github.com/johnross/second-brain" \
      org.opencontainers.image.version="0.5.0" \
      org.opencontainers.image.authors="John Ross"
