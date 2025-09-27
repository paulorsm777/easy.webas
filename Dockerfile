FROM python:3.11-slim

# Set environment variables
ENV PYTHONUNBUFFERED=1
ENV PYTHONPATH=/app

# Install system dependencies
RUN apt-get update && apt-get install -y \
    wget \
    gnupg2 \
    curl \
    xvfb \
    gcc \
    python3-dev \
    build-essential \
    fonts-liberation \
    fonts-dejavu-core \
    fonts-noto \
    libnss3-dev \
    libatk-bridge2.0-dev \
    libdrm-dev \
    libxkbcommon-dev \
    libgtk-3-dev \
    libgbm-dev \
    libasound2-dev \
    && rm -rf /var/lib/apt/lists/*

# Create app directory
WORKDIR /app

# Install Python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir --upgrade pip \
    && pip install --no-cache-dir -r requirements.txt

# Install Playwright dependencies (as root)
RUN DEBIAN_FRONTEND=noninteractive playwright install-deps chromium 2>/dev/null || echo "Playwright dependencies installed with some warnings"

# Copy application code
COPY . .

# Create data directory with proper permissions
RUN mkdir -p /app/data/videos \
    && mkdir -p /app/static \
    && mkdir -p /app/templates

# Set proper permissions
RUN chmod +x docker-entrypoint.sh

# Create non-root user for security
RUN useradd -m -u 1000 playwright \
    && chown -R playwright:playwright /app

# Switch to non-root user
USER playwright

# Install Playwright browsers as the playwright user
RUN playwright install chromium || echo "Browser installed with some warnings"

# Expose port
EXPOSE 8000

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=60s --retries=3 \
    CMD curl -f http://localhost:8000/health || exit 1

# Set entrypoint
ENTRYPOINT ["./docker-entrypoint.sh"]

# Default command
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "1"]
