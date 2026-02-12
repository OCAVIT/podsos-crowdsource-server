"""Сервер краудсорсинга стратегий обхода DPI — FastAPI на Railway."""

import asyncio
import logging

from fastapi import FastAPI, HTTPException, Header, Query
from fastapi.middleware.cors import CORSMiddleware

import db
from config import MAINTENANCE_TOKEN
from models import (
    CleanupResponse,
    HealthResponse,
    ReportRequest,
    ReportResponse,
    ServicesResponse,
    ServiceItem,
    StrategiesResponse,
    StrategyItem,
)

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(name)s] %(levelname)s: %(message)s")
logger = logging.getLogger("crowd.main")

app = FastAPI(
    title="PODSOS Crowdsource Server",
    version="0.1.0",
    description="Краудсорсинг стратегий обхода DPI для PODSOS ОЧКА",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


# -------------------------------------------------------------------
# Lifecycle
# -------------------------------------------------------------------

_CLEANUP_INTERVAL_SEC: int = 24 * 60 * 60  # 24 часа
_cleanup_task: asyncio.Task | None = None


async def _periodic_cleanup() -> None:
    """Фоновый цикл: cleanup каждые 24 часа."""
    while True:
        await asyncio.sleep(_CLEANUP_INTERVAL_SEC)
        try:
            stale, degraded = await db.run_cleanup()
            logger.info("Auto-cleanup done: stale=%d, degraded=%d", stale, degraded)
        except Exception as exc:
            logger.error("Auto-cleanup failed: %s", exc)


@app.on_event("startup")
async def startup():
    global _cleanup_task
    await db.init_pool()
    _cleanup_task = asyncio.create_task(_periodic_cleanup())
    logger.info("Server started (auto-cleanup every %ds)", _CLEANUP_INTERVAL_SEC)


@app.on_event("shutdown")
async def shutdown():
    global _cleanup_task
    if _cleanup_task is not None:
        _cleanup_task.cancel()
    await db.close_pool()
    logger.info("Server stopped")


# -------------------------------------------------------------------
# GET /strategies
# -------------------------------------------------------------------

@app.get("/strategies", response_model=StrategiesResponse)
async def get_strategies(
    provider: str = Query(..., min_length=1, description="ID провайдера"),
    service: str = Query(..., min_length=1, description="ID сервиса"),
):
    """Топ стратегий обхода для провайдера × сервиса."""
    rows = await db.get_strategies(provider, service)

    strategies = []
    for r in rows:
        total = r["success_count"] + r["fail_count"]
        rate = r["success_count"] / total if total > 0 else 0.0
        strategies.append(StrategyItem(
            id=r["id"],
            zapret_args=r["zapret_args"],
            success_count=r["success_count"],
            fail_count=r["fail_count"],
            success_rate=round(rate, 4),
            avg_latency_ms=round(r["avg_latency_ms"], 1),
            status=r["status"],
            last_confirmed=r["last_confirmed"],
        ))

    return StrategiesResponse(strategies=strategies, count=len(strategies))


# -------------------------------------------------------------------
# POST /report
# -------------------------------------------------------------------

@app.post("/report", response_model=ReportResponse)
async def post_report(body: ReportRequest):
    """Анонимный отчёт о стратегии обхода."""

    # Антиспам: rate limit по fingerprint
    allowed = await db.check_rate_limit(body.fingerprint)
    if not allowed:
        raise HTTPException(
            status_code=429,
            detail="Rate limit exceeded: max %d reports per hour" % db.MAX_REPORTS_PER_HOUR,
            headers={"Retry-After": "3600"},
        )

    strategy_id, strategy_status = await db.upsert_strategy(
        provider_id=body.provider_id,
        service_id=body.service_id,
        zapret_args=body.zapret_args,
        success=body.success,
        latency_ms=body.latency_ms,
        fingerprint=body.fingerprint,
        client_version=body.client_version,
    )

    return ReportResponse(
        status="accepted",
        strategy_id=strategy_id,
        strategy_status=strategy_status,
    )


# -------------------------------------------------------------------
# GET /services
# -------------------------------------------------------------------

@app.get("/services", response_model=ServicesResponse)
async def get_services(
    provider: str = Query(..., min_length=1, description="ID провайдера"),
):
    """Каталог сервисов с количеством стратегий для провайдера."""
    rows = await db.get_services(provider)

    services = [
        ServiceItem(
            id=r["id"],
            display_name=r["display_name"],
            category=r["category"],
            main_domain=r["main_domain"],
            icon_emoji=r.get("icon_emoji", ""),
            strategy_count=r["strategy_count"],
        )
        for r in rows
    ]

    return ServicesResponse(services=services)


# -------------------------------------------------------------------
# GET /health
# -------------------------------------------------------------------

@app.get("/health", response_model=HealthResponse)
async def health():
    """Статус сервера."""
    try:
        stats = await db.get_health_stats()
        return HealthResponse(
            status="ok",
            strategies_count=stats["total"],
            verified_count=stats["verified"],
            unconfirmed_count=stats["unconfirmed"],
            degraded_count=stats["degraded"],
            stale_count=stats["stale"],
            db_connected=True,
        )
    except Exception as exc:
        logger.error("Health check failed: %s", exc)
        return HealthResponse(
            status="error",
            strategies_count=0,
            verified_count=0,
            unconfirmed_count=0,
            degraded_count=0,
            stale_count=0,
            db_connected=False,
        )


# -------------------------------------------------------------------
# POST /maintenance/cleanup
# -------------------------------------------------------------------

@app.post("/maintenance/cleanup", response_model=CleanupResponse)
async def maintenance_cleanup(
    x_maintenance_token: str = Header(..., alias="X-Maintenance-Token"),
):
    """Cron-задача: пометить stale и degraded стратегии."""
    if x_maintenance_token != MAINTENANCE_TOKEN:
        raise HTTPException(status_code=403, detail="Invalid maintenance token")

    stale_marked, degraded_marked = await db.run_cleanup()

    return CleanupResponse(
        stale_marked=stale_marked,
        degraded_marked=degraded_marked,
    )


# -------------------------------------------------------------------
# Root
# -------------------------------------------------------------------

@app.get("/")
async def root():
    return {
        "service": "PODSOS Crowdsource Server",
        "version": "0.1.0",
        "endpoints": [
            "GET /strategies?provider=X&service=Y",
            "POST /report",
            "GET /services?provider=X",
            "GET /health",
        ],
    }
