"""HTTP request latency observability."""

import logging
import time

from fastapi import Request

logger = logging.getLogger(__name__)


async def request_latency_middleware(request: Request, call_next):
    start_time = time.time()
    response = await call_next(request)
    latency_ms = (time.time() - start_time) * 1000
    logger.info(
        "Request completed",
        extra={
            "method": request.method,
            "path": request.url.path,
            "status_code": response.status_code,
            "latency_ms": round(latency_ms, 2),
        },
    )
    return response
