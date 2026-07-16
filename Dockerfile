# Use Python base image
FROM python:3.10-slim

# Set work directory
WORKDIR /app

# Install system dependencies + PostgreSQL client
RUN apt-get update && apt-get install -y \
    build-essential \
    libpq-dev \
    postgresql-client \
    gcc \
    && rm -rf /var/lib/apt/lists/*

# Copy requirements
COPY requirements.txt .

# Install Python dependencies
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY . .

# Add permissions
RUN chmod +x entrypoint.sh

# Collect static at build time (best-effort; entrypoint collects again at runtime with real env)
RUN SECRET_KEY=build-only DEBUG=False python manage.py collectstatic --noinput || true

# Expose app port
EXPOSE 8000

# Entrypoint
ENTRYPOINT ["./entrypoint.sh"]

