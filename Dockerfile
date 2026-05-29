FROM python:3.12-slim

LABEL org.opencontainers.image.source=https://github.com/kadledav/immich-user-notify
LABEL org.opencontainers.image.description="immich-user-notify"
LABEL org.opencontainers.image.licenses=MIT

WORKDIR /app

# Install dependencies first to leverage Docker layer caching.
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY main.py .

CMD ["python", "main.py"]
