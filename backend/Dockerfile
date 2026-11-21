# Samme bilde brukes for API (standard) og arbeider (kommando: python -m bokbuzz.worker).
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    BOKBUZZ_MIGRATIONS_DIR=/app/migrations

WORKDIR /app
COPY pyproject.toml ./
COPY src ./src
COPY migrations ./migrations
RUN pip install --no-cache-dir '.[gcp]'

USER 1000
EXPOSE 8080
CMD ["sh", "-c", "exec uvicorn bokbuzz.main:app --host 0.0.0.0 --port ${PORT:-8080} --proxy-headers"]
