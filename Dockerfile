FROM python:3.12-slim

# The CI workflow (docker/metadata-action) sets the real image.source label at
# publish time from the repository, so this default is just a placeholder.
LABEL org.opencontainers.image.source=https://github.com/OWNER/immich-user-notify
LABEL org.opencontainers.image.description="Per-user ntfy notifications for Immich album changes"
LABEL org.opencontainers.image.licenses=MIT

ENV PYTHONUNBUFFERED=1 \
    DB_PATH=/data/state.db

WORKDIR /app

# Install dependencies first to leverage Docker layer caching.
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Application code + bundled locale files.
COPY main.py .
COPY immich_user_notify/ ./immich_user_notify/
COPY locales/ ./locales/

# SQLite state lives here; mount a volume to persist it across restarts.
RUN mkdir -p /data
VOLUME ["/data"]

CMD ["python", "main.py"]
