import asyncio
import json
from datetime import datetime
from typing import Optional, Dict, Any
import httpx
import structlog

from app.config import settings
from app.models import WebhookStatus

logger = structlog.get_logger()


class WebhookService:
    """Service for managing webhook notifications"""

    def __init__(self):
        self.client = httpx.AsyncClient(timeout=settings.WEBHOOK_TIMEOUT)
        self.retry_delays = [1, 2, 4]  # Exponential backoff

    async def send_webhook(self, webhook_url: str, payload: Dict[str, Any],
                          request_id: str, api_key_id: int) -> WebhookStatus:
        """Send webhook notification with retry logic"""
        if not webhook_url:
            return WebhookStatus.NOT_CONFIGURED

        logger.info("Sending webhook", webhook_url=webhook_url, request_id=request_id)

        for attempt in range(settings.MAX_WEBHOOK_RETRIES):
            try:
                response = await self.client.post(
                    webhook_url,
                    json=payload,
                    headers={
                        "Content-Type": "application/json",
                        "User-Agent": "PlaywrightServer/1.0",
                        "X-Request-ID": request_id,
                        "X-API-Key-ID": str(api_key_id)
                    }
                )

                if response.status_code < 400:
                    logger.info("Webhook sent successfully",
                              webhook_url=webhook_url,
                              request_id=request_id,
                              status_code=response.status_code,
                              attempt=attempt + 1)
                    return WebhookStatus.SENT

                else:
                    logger.warning("Webhook failed with HTTP error",
                                 webhook_url=webhook_url,
                                 request_id=request_id,
                                 status_code=response.status_code,
                                 attempt=attempt + 1)

            except httpx.TimeoutException:
                logger.warning("Webhook timeout",
                             webhook_url=webhook_url,
                             request_id=request_id,
                             attempt=attempt + 1)

            except Exception as e:
                logger.error("Webhook error",
                           webhook_url=webhook_url,
                           request_id=request_id,
                           error=str(e),
                           attempt=attempt + 1)

            # Wait before retry (except on last attempt)
            if attempt < settings.MAX_WEBHOOK_RETRIES - 1:
                await asyncio.sleep(self.retry_delays[attempt])

        logger.error("Webhook failed after all retries",
                   webhook_url=webhook_url,
                   request_id=request_id,
                   max_retries=settings.MAX_WEBHOOK_RETRIES)

        return WebhookStatus.FAILED

    async def create_execution_payload(self, request_id: str, api_key_id: int,
                                     status: str, execution_time: float,
                                     video_url: Optional[str] = None,
                                     result: Any = None,
                                     error: Optional[str] = None) -> Dict[str, Any]:
        """Create standardized webhook payload for execution events"""
        payload = {
            "event_type": "execution_completed",
            "request_id": request_id,
            "api_key_id": api_key_id,
            "status": status,
            "execution_time": execution_time,
            "timestamp": datetime.now().isoformat(),
            "video_url": video_url,
        }

        if result is not None:
            try:
                # Ensure result is JSON serializable
                json.dumps(result)
                payload["result"] = result
            except (TypeError, ValueError):
                payload["result"] = str(result)
                payload["result_note"] = "Result converted to string (not JSON serializable)"

        if error:
            payload["error"] = error

        return payload

    async def notify_execution_complete(self, request_id: str, api_key_id: int,
                                      webhook_url: Optional[str],
                                      status: str, execution_time: float,
                                      video_url: Optional[str] = None,
                                      result: Any = None,
                                      error: Optional[str] = None) -> WebhookStatus:
        """Send execution completion notification"""
        if not webhook_url:
            return WebhookStatus.NOT_CONFIGURED

        payload = await self.create_execution_payload(
            request_id=request_id,
            api_key_id=api_key_id,
            status=status,
            execution_time=execution_time,
            video_url=video_url,
            result=result,
            error=error
        )

        return await self.send_webhook(webhook_url, payload, request_id, api_key_id)

    async def notify_queue_position(self, request_id: str, api_key_id: int,
                                  webhook_url: Optional[str],
                                  queue_position: int,
                                  estimated_wait_time: float) -> WebhookStatus:
        """Send queue position notification"""
        if not webhook_url:
            return WebhookStatus.NOT_CONFIGURED

        payload = {
            "event_type": "queue_position",
            "request_id": request_id,
            "api_key_id": api_key_id,
            "queue_position": queue_position,
            "estimated_wait_time": estimated_wait_time,
            "timestamp": datetime.now().isoformat()
        }

        return await self.send_webhook(webhook_url, payload, request_id, api_key_id)

    async def notify_execution_started(self, request_id: str, api_key_id: int,
                                     webhook_url: Optional[str]) -> WebhookStatus:
        """Send execution started notification"""
        if not webhook_url:
            return WebhookStatus.NOT_CONFIGURED

        payload = {
            "event_type": "execution_started",
            "request_id": request_id,
            "api_key_id": api_key_id,
            "timestamp": datetime.now().isoformat()
        }

        return await self.send_webhook(webhook_url, payload, request_id, api_key_id)

    async def test_webhook(self, webhook_url: str, api_key_id: int) -> Dict[str, Any]:
        """Test webhook endpoint connectivity"""
        test_payload = {
            "event_type": "webhook_test",
            "api_key_id": api_key_id,
            "message": "This is a test webhook from Playwright Automation Server",
            "timestamp": datetime.now().isoformat()
        }

        start_time = datetime.now()

        try:
            response = await self.client.post(
                webhook_url,
                json=test_payload,
                headers={
                    "Content-Type": "application/json",
                    "User-Agent": "PlaywrightServer/1.0",
                    "X-Test": "true"
                }
            )

            end_time = datetime.now()
            response_time = (end_time - start_time).total_seconds()

            return {
                "success": True,
                "status_code": response.status_code,
                "response_time": response_time,
                "response_headers": dict(response.headers),
                "response_text": response.text[:500] if response.text else None,
                "message": "Webhook test successful"
            }

        except httpx.TimeoutException:
            return {
                "success": False,
                "error": "timeout",
                "message": f"Webhook timed out after {settings.WEBHOOK_TIMEOUT} seconds"
            }

        except Exception as e:
            return {
                "success": False,
                "error": type(e).__name__,
                "message": str(e)
            }

    async def validate_webhook_url(self, webhook_url: str) -> Dict[str, Any]:
        """Validate webhook URL format and accessibility"""
        import re
        from urllib.parse import urlparse

        # Basic URL validation
        url_pattern = re.compile(
            r'^https?://'  # http:// or https://
            r'(?:(?:[A-Z0-9](?:[A-Z0-9-]{0,61}[A-Z0-9])?\.)+[A-Z]{2,6}\.?|'  # domain...
            r'localhost|'  # localhost...
            r'\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3})'  # ...or ip
            r'(?::\d+)?'  # optional port
            r'(?:/?|[/?]\S+)$', re.IGNORECASE)

        if not url_pattern.match(webhook_url):
            return {
                "valid": False,
                "error": "Invalid URL format",
                "message": "URL must be a valid HTTP or HTTPS URL"
            }

        # Parse URL
        try:
            parsed = urlparse(webhook_url)
        except Exception as e:
            return {
                "valid": False,
                "error": "URL parsing failed",
                "message": str(e)
            }

        # Security checks
        if parsed.scheme not in ['http', 'https']:
            return {
                "valid": False,
                "error": "Invalid scheme",
                "message": "Only HTTP and HTTPS schemes are allowed"
            }

        # Discourage localhost for production
        if parsed.hostname in ['localhost', '127.0.0.1', '0.0.0.0']:
            return {
                "valid": True,
                "warning": "localhost_detected",
                "message": "Localhost URLs detected - ensure this is intended for development"
            }

        # Check for private IP ranges (optional warning)
        if parsed.hostname and self._is_private_ip(parsed.hostname):
            return {
                "valid": True,
                "warning": "private_ip",
                "message": "Private IP address detected - webhook may not be accessible from outside"
            }

        return {
            "valid": True,
            "message": "Webhook URL appears valid"
        }

    def _is_private_ip(self, hostname: str) -> bool:
        """Check if hostname is a private IP address"""
        try:
            import ipaddress
            ip = ipaddress.ip_address(hostname)
            return ip.is_private
        except ValueError:
            return False

    async def get_webhook_stats(self) -> Dict[str, Any]:
        """Get webhook statistics"""
        # This would typically query the database for webhook statistics
        # For now, return placeholder data
        return {
            "total_webhooks_sent": 0,
            "successful_webhooks": 0,
            "failed_webhooks": 0,
            "average_response_time": 0.0,
            "last_24h_webhooks": 0
        }

    async def close(self):
        """Close HTTP client"""
        await self.client.aclose()


# Global webhook service instance
webhook_service = WebhookService()