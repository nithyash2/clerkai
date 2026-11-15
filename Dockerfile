FROM python:3.12-slim

WORKDIR /app
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    CLERKAI_DATA=/app/data \
    CLERKAI_DB=/app/runs/clerkai.db

COPY pyproject.toml README.md ./
COPY src ./src
RUN pip install --no-cache-dir . && useradd --create-home appuser && mkdir -p /app/runs \
    && chown appuser /app/runs
COPY data ./data

USER appuser
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=3s CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8000/health')"
CMD ["uvicorn", "clerkai.api:app", "--host", "0.0.0.0", "--port", "8000"]
