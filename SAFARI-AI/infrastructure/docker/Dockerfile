# Build the visitor web app.
FROM node:22-slim AS web
WORKDIR /web
COPY apps/web/package.json apps/web/package-lock.json ./
RUN npm ci
COPY apps/web ./
RUN npm run build

# API + agent.
FROM python:3.12-slim
WORKDIR /app
ENV PYTHONUNBUFFERED=1
COPY pyproject.toml README.md ./
COPY services services
COPY apps/api apps/api
COPY apps/__init__.py apps/__init__.py
COPY apps/web/index.html apps/web/index.html
COPY apps/web/public apps/web/public
COPY --from=web /web/dist apps/web/dist
COPY knowledge knowledge
COPY evaluation evaluation
RUN pip install --no-cache-dir ".[postgres]"
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/v1/health')"
CMD ["uvicorn", "apps.api.main:app", "--host", "0.0.0.0", "--port", "8000", "--proxy-headers"]
