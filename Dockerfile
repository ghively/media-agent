# ── Stage 1: Build the React frontend ──────────────────────────────────
FROM node:22-slim AS frontend-build

WORKDIR /frontend
COPY frontend/package.json frontend/package-lock.json* ./
RUN npm ci --silent || npm install --silent
COPY frontend/ ./
RUN npm run build

# ── Stage 2: Python runtime ───────────────────────────────────────────
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
COPY --chown=media:media config/ ./config/

# Built frontend from Stage 1
COPY --from=frontend-build --chown=media:media /frontend/dist ./frontend/dist

# Run as non-root
USER media

EXPOSE 8088

HEALTHCHECK --interval=30s --timeout=10s --retries=3 \
    CMD curl -f http://localhost:8088/health || exit 1

CMD ["python", "-m", "src.main", "--serve"]
