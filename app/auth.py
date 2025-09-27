import time
from datetime import datetime
from typing import Optional, List
from fastapi import HTTPException, Security, Depends
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.util import get_remote_address
from slowapi.errors import RateLimitExceeded
import structlog

from app.database import get_api_key_by_value, update_api_key_usage
from app.models import ApiKeyResponse
from app.config import settings

logger = structlog.get_logger()
security = HTTPBearer()

# Rate limiter
limiter = Limiter(key_func=get_remote_address)

# In-memory rate limiting for API keys
api_key_rate_limits = {}


class AuthenticationError(HTTPException):
    def __init__(self, detail: str = "Invalid API key"):
        super().__init__(status_code=401, detail=detail)


class AuthorizationError(HTTPException):
    def __init__(self, detail: str = "Insufficient permissions"):
        super().__init__(status_code=403, detail=detail)


async def get_api_key_from_credentials(credentials: HTTPAuthorizationCredentials = Security(security)) -> ApiKeyResponse:
    """Extract and validate API key from credentials"""
    if not credentials or not credentials.credentials:
        raise AuthenticationError("API key required")

    api_key = await get_api_key_by_value(credentials.credentials)
    if not api_key:
        logger.warning("Invalid API key attempt", key_prefix=credentials.credentials[:8])
        raise AuthenticationError("Invalid API key")

    if not api_key.is_active:
        logger.warning("Inactive API key used", key_id=api_key.id)
        raise AuthenticationError("API key is disabled")

    if api_key.expires_at and datetime.now() > api_key.expires_at:
        logger.warning("Expired API key used", key_id=api_key.id, expires_at=api_key.expires_at)
        raise AuthenticationError("API key has expired")

    # Update usage tracking
    await update_api_key_usage(credentials.credentials)

    return api_key


async def check_api_key_rate_limit(api_key: ApiKeyResponse) -> bool:
    """Check if API key is within rate limits"""
    current_time = time.time()
    window_start = current_time - 60  # 1 minute window

    # Initialize if first request
    if api_key.id not in api_key_rate_limits:
        api_key_rate_limits[api_key.id] = []

    # Clean old requests outside the window
    api_key_rate_limits[api_key.id] = [
        req_time for req_time in api_key_rate_limits[api_key.id]
        if req_time > window_start
    ]

    # Check if under rate limit
    if len(api_key_rate_limits[api_key.id]) >= api_key.rate_limit_per_minute:
        logger.warning("Rate limit exceeded", key_id=api_key.id,
                      current_requests=len(api_key_rate_limits[api_key.id]),
                      limit=api_key.rate_limit_per_minute)
        return False

    # Add current request
    api_key_rate_limits[api_key.id].append(current_time)
    return True


async def get_current_api_key(credentials: HTTPAuthorizationCredentials = Security(security)) -> ApiKeyResponse:
    """Get current authenticated API key with rate limiting"""
    api_key = await get_api_key_from_credentials(credentials)

    # Check rate limiting
    if not await check_api_key_rate_limit(api_key):
        raise HTTPException(
            status_code=429,
            detail=f"Rate limit exceeded. Maximum {api_key.rate_limit_per_minute} requests per minute."
        )

    return api_key


def require_scopes(required_scopes: List[str]):
    """Dependency to require specific scopes"""
    async def check_scopes(api_key: ApiKeyResponse = Depends(get_current_api_key)):
        user_scopes = api_key.scopes

        # Admin scope grants all access
        if "admin" in user_scopes:
            return api_key

        # Check if user has all required scopes
        missing_scopes = [scope for scope in required_scopes if scope not in user_scopes]
        if missing_scopes:
            logger.warning("Insufficient scopes", key_id=api_key.id,
                         required=required_scopes, missing=missing_scopes)
            raise AuthorizationError(f"Missing required scopes: {', '.join(missing_scopes)}")

        return api_key

    return check_scopes


async def require_admin():
    """Dependency to require admin access"""
    async def check_admin(api_key: ApiKeyResponse = Depends(get_current_api_key)):
        if "admin" not in api_key.scopes:
            logger.warning("Admin access denied", key_id=api_key.id)
            raise AuthorizationError("Admin access required")
        return api_key

    return check_admin


# Convenience dependencies
require_execute = require_scopes(["execute"])
require_videos = require_scopes(["videos"])
require_dashboard = require_scopes(["dashboard"])


class RateLimitMiddleware:
    """Custom rate limiting middleware"""

    def __init__(self, app):
        self.app = app
        self.global_requests = []

    async def __call__(self, scope, receive, send):
        if scope["type"] == "http":
            current_time = time.time()
            window_start = current_time - 60  # 1 minute window

            # Clean old requests
            self.global_requests = [
                req_time for req_time in self.global_requests
                if req_time > window_start
            ]

            # Check global rate limit
            if len(self.global_requests) >= settings.GLOBAL_RATE_LIMIT_PER_MINUTE:
                response = {
                    "type": "http.response.start",
                    "status": 429,
                    "headers": [[b"content-type", b"application/json"]],
                }
                await send(response)

                body = {
                    "type": "http.response.body",
                    "body": b'{"detail":"Global rate limit exceeded"}',
                }
                await send(body)
                return

            # Add current request
            self.global_requests.append(current_time)

        await self.app(scope, receive, send)


def get_client_ip(request) -> str:
    """Get client IP address from request"""
    x_forwarded_for = request.headers.get("X-Forwarded-For")
    if x_forwarded_for:
        return x_forwarded_for.split(",")[0].strip()

    x_real_ip = request.headers.get("X-Real-IP")
    if x_real_ip:
        return x_real_ip

    return request.client.host if request.client else "unknown"


async def validate_api_key_scopes(api_key: ApiKeyResponse, required_scopes: List[str]) -> bool:
    """Validate that API key has required scopes"""
    if "admin" in api_key.scopes:
        return True

    return all(scope in api_key.scopes for scope in required_scopes)


async def log_api_access(api_key: ApiKeyResponse, endpoint: str, method: str, client_ip: str):
    """Log API access for audit trail"""
    logger.info("API access",
                key_id=api_key.id,
                key_name=api_key.name,
                endpoint=endpoint,
                method=method,
                client_ip=client_ip,
                scopes=api_key.scopes)