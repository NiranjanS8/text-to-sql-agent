FROM node:22-alpine AS frontend
WORKDIR /app
COPY package*.json vite.config.js index.html ./
COPY frontend ./frontend
RUN npm ci
RUN npm run build

FROM python:3.12-slim AS runtime
WORKDIR /app

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    DATABASE_URL=sqlite:////app/data/text_to_sql.db \
    LOG_LEVEL=INFO

RUN useradd --create-home --shell /usr/sbin/nologin appuser

COPY pyproject.toml README.md ./
COPY src ./src
COPY scripts ./scripts
COPY static ./static
COPY --from=frontend /app/static/react ./static/react

RUN pip install --no-cache-dir .
RUN mkdir -p /app/data && chown -R appuser:appuser /app

USER appuser
EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/health', timeout=3).read()"

CMD ["uvicorn", "text_to_sql_agent.main:app", "--host", "0.0.0.0", "--port", "8000"]
