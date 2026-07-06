# ── Stage 1: Build React dashboard ─────────────────────────────────────
FROM node:22-slim AS frontend
WORKDIR /build
COPY dashboard/package.json dashboard/package-lock.json* ./
RUN npm install --legacy-peer-deps
COPY dashboard/ ./
# Vite outputs to ../src/static relative to WORKDIR, so create that path
RUN mkdir -p /static && npx vite build --outDir /static --emptyOutDir

# ── Stage 2: Python app ────────────────────────────────────────────────
FROM python:3.12-slim

# System dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    ffmpeg \
    curl \
    git \
    && rm -rf /var/lib/apt/lists/*

# Create non-root user
RUN groupadd -r media && useradd -r -g media -d /app media

WORKDIR /app

# Python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Install additional tools
RUN pip install --no-cache-dir \
    yt-dlp \
    bandcamp-downloader \
    internetarchive \
    mutagen \
    audible-cli \
    apscheduler \
    jinja2 \
    python-telegram-bot>=21.0

# Application code
COPY --chown=media:media . .

# Copy React build from frontend stage
COPY --from=frontend /static /app/src/static

# Run as non-root
USER media

EXPOSE 8088

HEALTHCHECK --interval=30s --timeout=10s --retries=3 \
    CMD curl -f http://localhost:8088/health || exit 1

CMD ["python", "-m", "src.main", "--serve"]
