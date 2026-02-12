"""Pydantic-схемы запросов и ответов API краудсорсинга."""

from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# Запросы
# ---------------------------------------------------------------------------


class ReportRequest(BaseModel):
    """Тело POST /report — отчёт о стратегии."""

    provider_id: str = Field(..., min_length=1, max_length=50)
    service_id: str = Field(..., min_length=1, max_length=100)
    zapret_args: list[str] = Field(..., min_length=1)
    success: bool = True
    latency_ms: float = 0.0
    fingerprint: str = Field(..., min_length=16, max_length=128)
    client_version: str = ""


# ---------------------------------------------------------------------------
# Ответы
# ---------------------------------------------------------------------------


class StrategyItem(BaseModel):
    """Одна стратегия в выдаче GET /strategies."""

    id: int
    zapret_args: list[str]
    success_count: int
    fail_count: int
    success_rate: float
    avg_latency_ms: float
    status: str
    last_confirmed: datetime


class StrategiesResponse(BaseModel):
    """Ответ GET /strategies."""

    strategies: list[StrategyItem]
    count: int


class ReportResponse(BaseModel):
    """Ответ POST /report."""

    status: str  # "accepted" | "rate_limited"
    strategy_id: Optional[int] = None
    strategy_status: Optional[str] = None


class ServiceItem(BaseModel):
    """Один сервис в каталоге GET /services."""

    id: str
    display_name: str
    category: str
    main_domain: str
    icon_emoji: str = ""
    strategy_count: int = 0


class ServicesResponse(BaseModel):
    """Ответ GET /services."""

    services: list[ServiceItem]


class HealthResponse(BaseModel):
    """Ответ GET /health."""

    status: str
    strategies_count: int
    verified_count: int
    unconfirmed_count: int
    degraded_count: int
    stale_count: int
    db_connected: bool


class CleanupResponse(BaseModel):
    """Ответ POST /maintenance/cleanup."""

    stale_marked: int
    degraded_marked: int
