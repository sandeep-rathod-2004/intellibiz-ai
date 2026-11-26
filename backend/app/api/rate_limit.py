from collections import defaultdict, deque
from threading import Lock
from time import monotonic

from fastapi import HTTPException, Request, status

_requests: dict[tuple[str, str], deque[float]] = defaultdict(deque)
_lock = Lock()


def rate_limit(bucket_name: str, limit: int, window_seconds: int):
    def enforce(request: Request) -> None:
        client_host = request.client.host if request.client else "unknown"
        key = (bucket_name, client_host)
        now = monotonic()

        with _lock:
            timestamps = _requests[key]
            cutoff = now - window_seconds
            while timestamps and timestamps[0] <= cutoff:
                timestamps.popleft()

            if len(timestamps) >= limit:
                retry_after = max(1, int(window_seconds - (now - timestamps[0])))
                raise HTTPException(
                    status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                    detail="Too many requests. Please wait before trying again.",
                    headers={"Retry-After": str(retry_after)},
                )

            timestamps.append(now)
            if len(_requests) > 4096:
                for stale_key, stale_values in list(_requests.items()):
                    while stale_values and stale_values[0] <= cutoff:
                        stale_values.popleft()
                    if not stale_values:
                        _requests.pop(stale_key, None)

    return enforce
