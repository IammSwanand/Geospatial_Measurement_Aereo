import time
from collections import defaultdict
from threading import Lock
from typing import Dict, List, Optional
from fastapi import Request, HTTPException, status
from app.core.config import settings

class InMemorySlidingWindowRateLimiter:
    """
    Thread-safe sliding-window rate limiter per client IP address.
    Supports reverse-proxy headers (X-Forwarded-For) and automatic memory cleanup.
    """

    def __init__(self):
        self._history: Dict[str, List[float]] = defaultdict(list)
        self._lock = Lock()
        self._last_cleanup = time.time()

    def _get_client_ip(self, request: Request) -> str:
        forwarded = request.headers.get("X-Forwarded-For")
        if forwarded:
            return forwarded.split(",")[0].strip()
        if request.client and request.client.host:
            return request.client.host
        return "127.0.0.1"

    def _cleanup_expired_entries(self, now: float, window_seconds: int = 60):
        """Purges old timestamps to prevent memory leaks."""
        if now - self._last_cleanup > 300:  # Prune every 5 minutes
            cutoff = now - window_seconds
            keys_to_delete = []
            for ip, timestamps in self._history.items():
                active = [t for t in timestamps if t > cutoff]
                if active:
                    self._history[ip] = active
                else:
                    keys_to_delete.append(ip)
            for k in keys_to_delete:
                del self._history[k]
            self._last_cleanup = now

    def check(self, request: Request, max_requests: int, window_seconds: int = 60, bucket: Optional[str] = None) -> None:
        if not settings.RATE_LIMIT_ENABLED:
            return

        ip = self._get_client_ip(request)
        bucket_key = f"{ip}:{bucket or max_requests}"
        now = time.time()
        cutoff = now - window_seconds

        with self._lock:
            self._cleanup_expired_entries(now, window_seconds)
            timestamps = self._history[bucket_key]
            
            # Keep only timestamps in the current window
            valid_timestamps = [t for t in timestamps if t > cutoff]
            self._history[bucket_key] = valid_timestamps

            if len(valid_timestamps) >= max_requests:
                oldest_in_window = valid_timestamps[0]
                retry_after = max(1, int(oldest_in_window + window_seconds - now))
                raise HTTPException(
                    status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                    detail=f"Rate limit exceeded: Maximum {max_requests} requests per {window_seconds}s. Try again in {retry_after}s.",
                    headers={"Retry-After": str(retry_after)},
                )

            self._history[bucket_key].append(now)

rate_limiter = InMemorySlidingWindowRateLimiter()

def rate_limit(max_requests: int = 60, window_seconds: int = 60, bucket: Optional[str] = None):
    """FastAPI dependency for endpoint-level rate limiting."""
    def dependency(request: Request):
        rate_limiter.check(request, max_requests=max_requests, window_seconds=window_seconds, bucket=bucket)
    return dependency
