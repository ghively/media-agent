FROM python:3.12-slim

# System dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    ffmpeg \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Create non-root user
RUN groupadd -r media && useradd -r -g media -d /app media

WORKDIR /app

# Python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Application code
COPY --chown=media:media . .
COPY --chown=media:media config/ ./config/

# Run as non-root
USER media

EXPOSE 8088

HEALTHCHECK --interval=30s --timeout=10s --retries=3 \
    CMD curl -f http://localhost:8088/health || exit 1

CMD ["python", "-m", "src.main", "--serve"]
