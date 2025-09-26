import time
from datetime import datetime, timedelta
from typing import Dict, Optional, List
from collections import defaultdict
from fastapi import HTTPException, Security, Depends
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
import asyncio

from .database import db
from .models import ApiKeyResponse
from .config import settings


class RateLimiter:
    def __init__(self):
        self._requests: Dict[str, List[float]] = defaultdict(list)
        self._global_requests: List[float] = []
        self._lock = asyncio.Lock()

    async def check_rate_limit(
        self, identifier: str, limit_per_minute: int, is_global: bool = False
    ) -> bool:
        """Check if request is within rate limit"""
        async with self._lock:
            now = time.time()
            minute_ago = now - 60

            if is_global:
                # Clean old requests
                self._global_requests = [
                    req_time
                    for req_time in self._global_requests
                    if req_time > minute_ago
                ]

                if len(self._global_requests) >= settings.global_rate_limit_per_minute:
                    return False

                self._global_requests.append(now)
                return True
            else:
                # Clean old requests for this identifier
                self._requests[identifier] = [
                    req_time
                    for req_time in self._requests[identifier]
                    if req_time > minute_ago
                ]

                if len(self._requests[identifier]) >= limit_per_minute:
                    return False

                self._requests[identifier].append(now)
                return True

    async def get_remaining_requests(
        self, identifier: str, limit_per_minute: int
    ) -> int:
        """Get remaining requests for identifier"""
        async with self._lock:
            now = time.time()
            minute_ago = now - 60

            recent_requests = [
                req_time
                for req_time in self._requests[identifier]
                if req_time > minute_ago
            ]
            return max(0, limit_per_minute - len(recent_requests))


class AuthManager:
    def __init__(self):
        self.rate_limiter = RateLimiter()
        self._auth_cache: Dict[str, tuple] = {}  # key -> (api_key_obj, cache_time)
        self._cache_ttl = 300  # 5 minutes

    async def get_api_key(self, key_value: str) -> Optional[ApiKeyResponse]:
        """Get API key with caching"""
        now = time.time()

        # Check cache first
        if key_value in self._auth_cache:
            cached_key, cache_time = self._auth_cache[key_value]
            if now - cache_time < self._cache_ttl:
                return cached_key

        # Fetch from database
        api_key = await db.get_api_key_by_value(key_value)

        if api_key:
            # Cache the result
            self._auth_cache[key_value] = (api_key, now)

        return api_key

    async def validate_api_key(
        self, key_value: str, required_scopes: List[str] = None
    ) -> ApiKeyResponse:
        """Validate API key and check scopes"""
        api_key = await self.get_api_key(key_value)

        if not api_key:
            raise HTTPException(status_code=401, detail="Invalid API key")

        if not api_key.is_active:
            raise HTTPException(status_code=401, detail="API key is disabled")

        # Check expiration
        if api_key.expires_at and datetime.now() > api_key.expires_at:
            raise HTTPException(status_code=401, detail="API key has expired")

        # Check scopes
        if required_scopes:
            user_scopes = set(api_key.scopes)
            required_scopes_set = set(required_scopes)

            if not required_scopes_set.issubset(user_scopes):
                missing_scopes = required_scopes_set - user_scopes
                raise HTTPException(
                    status_code=403,
                    detail=f"Missing required scopes: {', '.join(missing_scopes)}",
                )

        return api_key

    async def check_rate_limits(self, api_key: ApiKeyResponse) -> None:
        """Check both global and per-key rate limits"""
        # Check global rate limit
        global_ok = await self.rate_limiter.check_rate_limit(
            "global", settings.global_rate_limit_per_minute, is_global=True
        )

        if not global_ok:
            raise HTTPException(
                status_code=429,
                detail="Global rate limit exceeded. Please try again later.",
                headers={"Retry-After": "60"},
            )

        # Check per-key rate limit
        key_ok = await self.rate_limiter.check_rate_limit(
            api_key.key_value, api_key.rate_limit_per_minute
        )

        if not key_ok:
            remaining_time = 60  # Simplified - could calculate exact time
            raise HTTPException(
                status_code=429,
                detail=f"API key rate limit exceeded. Limit: {api_key.rate_limit_per_minute}/minute",
                headers={"Retry-After": str(remaining_time)},
            )

    async def authenticate_and_authorize(
        self, key_value: str, required_scopes: List[str] = None
    ) -> ApiKeyResponse:
        """Full authentication and authorization flow"""
        # Validate API key and scopes
        api_key = await self.validate_api_key(key_value, required_scopes)

        # Check rate limits
        await self.check_rate_limits(api_key)

        # Update usage tracking
        await db.update_api_key_usage(api_key.id)

        return api_key

    def invalidate_cache(self, key_value: str = None):
        """Invalidate auth cache"""
        if key_value:
            self._auth_cache.pop(key_value, None)
        else:
            self._auth_cache.clear()


# Global auth manager
auth_manager = AuthManager()

# FastAPI security scheme
security = HTTPBearer()


async def get_current_api_key(
    credentials: HTTPAuthorizationCredentials = Security(security),
    required_scopes: List[str] = None,
) -> ApiKeyResponse:
    """FastAPI dependency for API key authentication"""
    return await auth_manager.authenticate_and_authorize(
        credentials.credentials, required_scopes
    )


def require_scopes(scopes: List[str]):
    """Decorator to require specific scopes"""

    async def dependency(
        credentials: HTTPAuthorizationCredentials = Security(security),
    ) -> ApiKeyResponse:
        return await auth_manager.authenticate_and_authorize(
            credentials.credentials, scopes
        )

    return dependency


# Common dependencies
async def require_execute_scope(
    api_key: ApiKeyResponse = Depends(require_scopes(["execute"])),
) -> ApiKeyResponse:
    return api_key


async def require_admin_scope(
    api_key: ApiKeyResponse = Depends(require_scopes(["admin"])),
) -> ApiKeyResponse:
    return api_key


async def require_dashboard_scope(
    api_key: ApiKeyResponse = Depends(require_scopes(["dashboard"])),
) -> ApiKeyResponse:
    return api_key


async def require_videos_scope(
    api_key: ApiKeyResponse = Depends(require_scopes(["videos"])),
) -> ApiKeyResponse:
    return api_key
