"""Конфигурация сервера краудсорсинга стратегий из переменных окружения."""

import os

DATABASE_URL: str = os.environ.get(
    "DATABASE_URL",
    "postgresql://localhost:5432/podsos_crowd",
)

CRON_SECRET: str = os.environ.get("CRON_SECRET", "change-me-in-production")

MAX_REPORTS_PER_HOUR: int = int(os.environ.get("MAX_REPORTS_PER_HOUR", "10"))

# Минимальное количество голосов для промоута в verified
MIN_VOTES_VERIFIED: int = 5

# Пороги success_rate
VERIFIED_RATE_THRESHOLD: float = 0.60
STALE_RATE_THRESHOLD: float = 0.40

# Дней без подтверждения до stale
STALE_DAYS: int = 7

# Максимум стратегий в выдаче
MAX_STRATEGIES_RESPONSE: int = 5

# Минимум стратегий по провайдеру перед fallback на "all"
MIN_PROVIDER_STRATEGIES: int = 3

# Порог success_rate для fallback-стратегий
FALLBACK_SUCCESS_RATE: float = 0.70
