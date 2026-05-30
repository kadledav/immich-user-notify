FROM python:3.12-slim

LABEL org.opencontainers.image.source=https://github.com/kadledav/immich-user-notify
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
