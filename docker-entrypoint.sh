#!/bin/bash
set -e

echo "🎭 Starting Playwright Automation Server..."

# Check if running as root and warn
if [ "$(id -u)" = "0" ]; then
    echo "⚠️  Warning: Running as root user. Consider using a non-root user for production."
fi

# Create data directories if they don't exist
echo "📁 Setting up data directories..."
mkdir -p /app/data/videos

# Set permissions if running as root
if [ "$(id -u)" = "0" ]; then
    chown -R 1000:1000 /app/data
fi

# Initialize database if it doesn't exist
echo "🗄️  Checking database..."
if [ ! -f /app/data/database.db ]; then
    echo "📦 Initializing database..."
    python3 -c "
import asyncio
from app.database import init_database
asyncio.run(init_database())
print('Database initialized successfully')
"
else
    echo "✅ Database already exists"
fi

# Ensure admin API key exists
echo "🔑 Ensuring admin API key exists..."
python3 -c "
import asyncio
from app.database import ensure_admin_key
asyncio.run(ensure_admin_key())
print('Admin key verified')
"

# Check system requirements
echo "🔍 Checking system requirements..."

# Check available memory
AVAILABLE_MEMORY=$(free -m | awk 'NR==2{printf "%d", $7}')
if [ "$AVAILABLE_MEMORY" -lt 512 ]; then
    echo "⚠️  Warning: Low available memory (${AVAILABLE_MEMORY}MB). Recommend at least 512MB free."
fi

# Check disk space
AVAILABLE_DISK=$(df /app/data | awk 'NR==2{print $4}')
if [ "$AVAILABLE_DISK" -lt 1048576 ]; then  # 1GB in KB
    echo "⚠️  Warning: Low disk space. Recommend at least 1GB free for video storage."
fi

# Test Playwright installation
echo "🌐 Testing Playwright installation..."
python3 -c "
from playwright.sync_api import sync_playwright
try:
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        browser.close()
    print('✅ Playwright is working correctly')
except Exception as e:
    print(f'❌ Playwright test failed: {e}')
    exit(1)
"

# Start cleanup service in background
echo "🧹 Starting cleanup service..."
python3 -c "
import asyncio
from app.cleanup import start_cleanup_scheduler
try:
    asyncio.run(start_cleanup_scheduler())
    print('✅ Cleanup service started')
except Exception as e:
    print(f'⚠️  Cleanup service warning: {e}')
" &

# Wait a moment for cleanup service to start
sleep 2

echo "🚀 Starting FastAPI server..."
echo "📊 Dashboard will be available at http://localhost:8000/dashboard?api_key=<your_key>"
echo "📚 API documentation at http://localhost:8000/docs"
echo "❤️  Health check at http://localhost:8000/health"
echo ""

# Execute the main command
exec "$@"
