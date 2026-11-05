# SafariAI backend: FastAPI + agent. Serves the API only; the frontend has its own image.
FROM python:3.12-slim
WORKDIR /app
ENV PYTHONUNBUFFERED=1 \
    SAFARI_DATA_DIR=/data
COPY pyproject.toml ./
COPY services services
COPY api api
RUN pip install --no-cache-dir ".[postgres]"
COPY assets assets
COPY knowledge knowledge
COPY evaluation evaluation
VOLUME /data
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/v1/health')"
CMD ["uvicorn", "api.main:app", "--host", "0.0.0.0", "--port", "8000", "--proxy-headers"]
