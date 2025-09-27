# 🎭 Playwright Automation Server

Advanced Playwright script execution server with queue management, video recording, API key authentication, and comprehensive monitoring dashboard.

## ✨ Features

- **🚀 Script Execution**: Execute Playwright scripts with queue management and priority system
- **🎥 Video Recording**: Automatic video recording of all executions (720p)
- **🔐 API Key Management**: Secure authentication with scoped permissions
- **📊 Real-time Dashboard**: Web-based monitoring and analytics
- **🔄 Queue System**: Intelligent queue with priority and resource management
- **📈 Monitoring**: Health checks, metrics, and resource monitoring
- **🪝 Webhooks**: Notification system for execution events
- **📋 Script Templates**: Pre-built script templates for common tasks
- **🛡️ Security**: Advanced script validation and security scanning
- **🧹 Auto-cleanup**: Automatic cleanup of old videos and data

## 🚀 Quick Start

### Docker (Recommended)

1. **Clone and start the server:**
```bash
git clone <repository>
cd easy.webas
docker-compose up -d
```

2. **Access the dashboard:**
```bash
# Get the admin API key
docker-compose logs playwright-server | grep "admin-super-secret-key"

# Open dashboard
open http://localhost:8000/dashboard?api_key=admin-super-secret-key-2024
```

3. **Execute your first script:**
```bash
curl -X POST "http://localhost:8000/execute" \
  -H "Authorization: Bearer admin-super-secret-key-2024" \
  -H "Content-Type: application/json" \
  -d '{
    "script": "from playwright.async_api import async_playwright\n\nasync def main():\n    async with async_playwright() as p:\n        browser = await p.chromium.launch()\n        page = await browser.new_page()\n        await page.goto(\"https://example.com\")\n        title = await page.title()\n        await browser.close()\n        return {\"title\": title, \"status\": \"success\"}",
    "timeout": 60,
    "priority": 3
  }'
```

## 📖 API Documentation

### Authentication
All API requests require an API key in the Authorization header:
```
Authorization: Bearer your-api-key-here
```

### Core Endpoints

#### Execute Script
```http
POST /execute
Content-Type: application/json
Authorization: Bearer <api-key>

{
  "script": "from playwright.async_api import async_playwright\n\nasync def main():\n    async with async_playwright() as p:\n        browser = await p.chromium.launch()\n        page = await browser.new_page()\n        await page.goto('https://example.com')\n        title = await page.title()\n        await browser.close()\n        return {\"title\": title}",
  "timeout": 60,
  "priority": 1,
  "tags": ["test", "example"],
  "webhook_url": "https://your-webhook.com/callback"
}
```

#### Get Templates
```http
GET /templates
Authorization: Bearer <api-key>
```

#### Health Check
```http
GET /health
```

#### Dashboard
```http
GET /dashboard?api_key=<api-key>
```

### Admin Endpoints (Admin API Key Required)

#### Create API Key
```http
POST /admin/api-keys
Authorization: Bearer <admin-api-key>

{
  "name": "My API Key",
  "scopes": ["execute", "videos", "dashboard"],
  "rate_limit_per_minute": 30
}
```

#### List API Keys
```http
GET /admin/api-keys
Authorization: Bearer <admin-api-key>
```

#### Analytics
```http
GET /admin/analytics
Authorization: Bearer <admin-api-key>
```

## 🎯 Script Templates

### Available Templates

1. **Google Search** - Web scraping example
2. **Form Filling** - Automated form submission
3. **Screenshot Capture** - Page information extraction
4. **E-commerce Product Check** - Product monitoring
5. **Social Media Post** - Social media data extraction
6. **API Endpoint Test** - API testing through browser
7. **Login and Navigate** - Authentication flows
8. **Data Table Extraction** - HTML table scraping

### Using Templates
```bash
# List all templates
curl "http://localhost:8000/templates" \
  -H "Authorization: Bearer <api-key>"

# Get specific template
curl "http://localhost:8000/templates/google_search" \
  -H "Authorization: Bearer <api-key>"
```

## 🔧 Configuration

### Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `ADMIN_API_KEY` | `admin-super-secret-key-2024` | Master admin API key |
| `MAX_CONCURRENT_EXECUTIONS` | `10` | Maximum parallel executions |
| `MAX_QUEUE_SIZE` | `100` | Maximum queue size |
| `VIDEO_RETENTION_DAYS` | `7` | Days to keep videos |
| `BROWSER_POOL_SIZE` | `10` | Browser pool size |
| `GLOBAL_RATE_LIMIT_PER_MINUTE` | `60` | Global rate limit |

### Docker Compose Profiles

- **Default**: Basic server only
- **Production**: Server + Nginx reverse proxy
- **Monitoring**: Server + Prometheus + Grafana

```bash
# Start with Nginx
docker-compose --profile production up -d

# Start with monitoring
docker-compose --profile monitoring up -d
```

## 📊 Monitoring & Analytics

### Dashboard Features
- Real-time system health monitoring
- Queue status and execution metrics
- Video storage statistics
- Browser pool status
- Resource usage tracking
- Warning system for resource limits

### Metrics Endpoint
Prometheus-compatible metrics available at `/metrics`:
- Queue size and active executions
- System resource usage
- Service health status
- API key usage statistics

### Health Checks
Comprehensive health check at `/health`:
- Database connectivity
- Browser pool health
- Queue status
- Disk space availability
- Memory and CPU usage

## 🛡️ Security Features

### Script Validation
- AST-based security scanning
- Forbidden import detection
- Dangerous function identification
- Performance analysis
- Complexity estimation

### API Security
- API key authentication with scopes
- Rate limiting (global and per-key)
- Request validation
- Resource limits enforcement

### Container Security
- Non-root user execution
- Read-only file system where possible
- Resource limits (CPU/memory)
- Network isolation

## 🎥 Video Management

### Video Features
- Automatic recording in 720p (1280x720)
- Organized storage by date
- Automatic cleanup after retention period
- Direct video access with API key
- Video metadata and statistics

### Video URLs
```
GET /video/{request_id}/{api_key}
GET /video/{request_id}/info
```

## 🪝 Webhooks

### Webhook Events
- `execution_started` - When script execution begins
- `execution_completed` - When script execution finishes
- `queue_position` - Queue position updates

### Webhook Payload Example
```json
{
  "event_type": "execution_completed",
  "request_id": "uuid-here",
  "api_key_id": 123,
  "status": "completed",
  "execution_time": 15.5,
  "video_url": "http://localhost:8000/video/uuid/api-key",
  "result": {...},
  "timestamp": "2025-01-15T10:30:00Z"
}
```

## 🧹 Maintenance

### Automatic Cleanup
- Daily video cleanup at 2 AM (configurable)
- Old execution records cleanup
- Rate limiting data cleanup
- Database optimization

### Manual Cleanup
```bash
# Force video cleanup
curl -X DELETE "http://localhost:8000/admin/videos/cleanup" \
  -H "Authorization: Bearer <admin-api-key>"
```

## 🚨 Troubleshooting

### Common Issues

1. **Browser Launch Failures**
   - Ensure sufficient memory (recommend 2GB+)
   - Check `/dev/shm` mount for Docker
   - Verify Playwright installation

2. **Video Recording Issues**
   - Check disk space availability
   - Verify video directory permissions
   - Monitor storage usage in dashboard

3. **High Memory Usage**
   - Reduce `BROWSER_POOL_SIZE`
   - Lower `MAX_CONCURRENT_EXECUTIONS`
   - Check for memory leaks in scripts

4. **Queue Backing Up**
   - Monitor script execution times
   - Check for stuck executions
   - Increase timeout values if needed

### Logs
```bash
# View server logs
docker-compose logs -f playwright-server

# View specific service logs
docker-compose logs cleanup-service
```

### Health Diagnostics
```bash
# Check system health
curl http://localhost:8000/health

# Get detailed metrics
curl http://localhost:8000/metrics

# Check queue status
curl "http://localhost:8000/queue/status" \
  -H "Authorization: Bearer <api-key>"
```

## 📦 Development

### Local Development
```bash
# Install dependencies
pip install -r requirements.txt

# Install Playwright
playwright install chromium

# Run server
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

### Testing
```bash
# Test script validation
curl -X POST "http://localhost:8000/validate" \
  -H "Authorization: Bearer <api-key>" \
  -H "Content-Type: application/json" \
  -d '{"script": "async def main(): return \"test\""}'

# Test webhook
curl -X POST "http://localhost:8000/admin/webhook/test" \
  -H "Authorization: Bearer <admin-api-key>" \
  -H "Content-Type: application/json" \
  -d '{"webhook_url": "https://httpbin.org/post"}'
```

## 📄 License

This project is licensed under the MIT License.

## 🤝 Contributing

1. Fork the repository
2. Create a feature branch
3. Make your changes
4. Add tests if applicable
5. Submit a pull request

## 📞 Support

For issues and questions:
1. Check the troubleshooting section
2. Review the logs
3. Check system health at `/health`
4. Open an issue with details

---

**Happy Automating! 🎭✨**
