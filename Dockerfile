# Lab Server File Organizer — minimal, no build step (frontend is static files).
FROM python:3.11-slim

WORKDIR /app

# Install deps first for layer caching.
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# App code (backend + static frontend).
COPY backend/ backend/
COPY frontend/ frontend/

# Run as an unprivileged user; it owns /app so the audit log is writable.
RUN useradd --create-home --uid 10001 app && chown -R app /app
USER app

# Defaults; override the rest at `docker run -e ...` (READ_ONLY, AUTH_TOKEN,
# ANTHROPIC_API_KEY, RATE_LIMIT, PATH_PRIVACY, MOVES_LOG, MAX_CHILDREN).
# Mount the directory to organize at /data and point LAB_ROOT there.
ENV LAB_ROOT=/data \
    BIND_HOST=0.0.0.0 \
    BIND_PORT=8000

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=3s --start-period=5s --retries=3 \
  CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/healthz').status==200 else 1)"

# Bind 0.0.0.0 *inside* the container; publish only to localhost on the host:
#   docker run -p 127.0.0.1:8000:8000 -v /srv/lab:/data:ro lab-organizer   (browse)
#   docker run -p 127.0.0.1:8000:8000 -v /srv/lab:/data    lab-organizer   (organize)
CMD ["uvicorn", "backend.main:app", "--host", "0.0.0.0", "--port", "8000"]
