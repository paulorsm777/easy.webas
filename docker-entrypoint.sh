#!/bin/bash
set -e

echo "🚀 Playwright Automation Server - Starting..."

# Function to log with timestamp
log() {
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] $1"
}

# Check if data directory exists and is writable
log "Checking data directory..."
if [ ! -d "/app/data" ]; then
    log "Creating data directory..."
    mkdir -p /app/data/videos
fi

if [ ! -w "/app/data" ]; then
    log "ERROR: Data directory is not writable"
    exit 1
fi

# Initialize database if it doesn't exist
if [ ! -f "/app/data/database.db" ]; then
    log "Initializing database..."
    python -c "
import asyncio
from app.database import init_database
asyncio.run(init_database())
print('Database initialized successfully')
" || {
        log "ERROR: Failed to initialize database"
        exit 1
    }
else
    log "Database already exists"
fi

# Ensure admin API key exists
log "Ensuring admin API key exists..."
python -c "
import asyncio
from app.database import ensure_admin_key
asyncio.run(ensure_admin_key())
print('Admin API key verified')
" || {
    log "ERROR: Failed to ensure admin API key"
    exit 1
}

# Check Playwright installation
log "Verifying Playwright installation..."
python -c "
from playwright.sync_api import sync_playwright
with sync_playwright() as p:
    browser = p.chromium.launch()
    print('Playwright verification successful')
    browser.close()
" || {
    log "ERROR: Playwright verification failed"
    exit 1
}

# Display configuration
log "Configuration:"
log "  - Max concurrent executions: ${MAX_CONCURRENT_EXECUTIONS:-10}"
log "  - Max queue size: ${MAX_QUEUE_SIZE:-100}"
log "  - Video retention days: ${VIDEO_RETENTION_DAYS:-7}"
log "  - Browser pool size: ${BROWSER_POOL_SIZE:-10}"
log "  - Admin API key: ${ADMIN_API_KEY:0:8}..."

# Check system resources
log "System resources:"
log "  - Memory: $(free -h | awk '/^Mem:/ {print $2}') total"
log "  - Disk space: $(df -h /app | awk 'NR==2 {print $4}') available"
log "  - CPU cores: $(nproc)"

# Start cleanup scheduler in background if enabled
if [ "${ENABLE_CLEANUP_SCHEDULER:-true}" = "true" ]; then
    log "Starting cleanup scheduler..."
    python -c "
import asyncio
from app.video_service import cleanup_scheduler
async def start_cleanup():
    await cleanup_scheduler.start()
    print('Cleanup scheduler started')
    # Keep running
    try:
        while True:
            await asyncio.sleep(60)
    except KeyboardInterrupt:
        await cleanup_scheduler.stop()

asyncio.run(start_cleanup())
" &
    CLEANUP_PID=$!
    log "Cleanup scheduler started with PID: $CLEANUP_PID"
fi

# Trap signals for graceful shutdown
trap_handler() {
    log "Received signal, shutting down gracefully..."

    if [ ! -z "$CLEANUP_PID" ]; then
        log "Stopping cleanup scheduler..."
        kill $CLEANUP_PID 2>/dev/null || true
    fi

    log "Shutdown complete"
    exit 0
}

trap trap_handler SIGTERM SIGINT

# Display startup message
log "🎭 Playwright Automation Server is ready!"
log "📊 Dashboard: http://localhost:8000/dashboard?api_key=${ADMIN_API_KEY}"
log "📖 API Documentation: http://localhost:8000/docs"
log "🔍 Health Check: http://localhost:8000/health"

# Execute the main command
log "Starting main application: $@"
exec "$@"
