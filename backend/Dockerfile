FROM python:3.11-slim

WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Copy requirements first for better caching
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY app/ ./app/
COPY prompts.yaml.example ./prompts.yaml

# Copy alembic for database migrations (run automatically on startup)
COPY alembic.ini .
COPY alembic/ ./alembic/

# Create data directory
RUN mkdir -p /app/data

# Environment
ENV DATABASE_PATH=/app/data/reader.db
ENV LOG_FILE=/app/data/app.log

EXPOSE 8000

# Run with gunicorn (timeout prevents hung workers, max-requests prevents memory leaks)
CMD ["gunicorn", "app.main:app", "-k", "uvicorn.workers.UvicornWorker", "-b", "0.0.0.0:8000", "--workers", "1", "--timeout", "120", "--max-requests", "1000", "--max-requests-jitter", "50"]
