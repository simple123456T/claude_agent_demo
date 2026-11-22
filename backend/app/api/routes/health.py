import logging
import time
from collections.abc import Callable
from typing import Literal

from fastapi import APIRouter, status
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from app.db.probes import probe_milvus, probe_postgres, probe_redis

router = APIRouter(prefix="/health", tags=["health"])
logger = logging.getLogger(__name__)


class ServiceHealth(BaseModel):
    status: Literal["up", "down"]
    required: bool
    latency_ms: int | None = None
    error: str | None = None


class ReadinessResponse(BaseModel):
    status: Literal["ready", "degraded", "not_ready"]
    services: dict[str, ServiceHealth]


@router.get("/live")
def liveness() -> dict[str, str]:
    return {"status": "ok"}


@router.get("/ready", response_model=ReadinessResponse)
def readiness() -> JSONResponse:
    services = {
        "postgresql": _probe("postgresql", probe_postgres, required=True),
        "redis": _probe("redis", probe_redis, required=True),
        "milvus": _probe("milvus", probe_milvus, required=False),
    }
    required_down = any(item.required and item.status == "down" for item in services.values())
    optional_down = any(not item.required and item.status == "down" for item in services.values())
    overall = "not_ready" if required_down else "degraded" if optional_down else "ready"
    response = ReadinessResponse(status=overall, services=services)
    return JSONResponse(
        status_code=status.HTTP_503_SERVICE_UNAVAILABLE if required_down else status.HTTP_200_OK,
        content=response.model_dump(),
    )


def _probe(name: str, probe: Callable[[], None], required: bool) -> ServiceHealth:
    started = time.perf_counter()
    try:
        probe()
    except Exception as exc:
        # Exception messages can include connection URLs, so only expose the class name.
        logger.warning("%s health check failed: %s", name, type(exc).__name__)
        return ServiceHealth(status="down", required=required, error=type(exc).__name__)
    latency_ms = round((time.perf_counter() - started) * 1000)
    return ServiceHealth(status="up", required=required, latency_ms=latency_ms)
