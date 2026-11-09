# SafariAI backend: FastAPI + agent. Serves the API only; the frontend has its own image.
FROM python:3.12-slim
WORKDIR /app
ENV PYTHONUNBUFFERED=1 \
    SAFARI_DATA_DIR=/data \
    PORT=8000
COPY pyproject.toml ./
COPY services services
COPY api api
RUN pip install --no-cache-dir ".[postgres]"
COPY assets assets
COPY knowledge knowledge
COPY evaluation evaluation
# Applied on start by the Postgres store, so a fresh database needs no manual setup.
COPY postgres postgres
RUN mkdir -p /data
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s CMD python -c "import os, urllib.request; urllib.request.urlopen(f'http://127.0.0.1:{os.environ[\"PORT\"]}/v1/health')"
# Hosts such as Render set PORT; the default 8000 matches docker-compose.
CMD ["sh", "-c", "exec uvicorn api.main:app --host 0.0.0.0 --port \"$PORT\" --proxy-headers"]
