"""Слой базы данных — asyncpg пул и все SQL-запросы."""

import hashlib
import logging
import os
from pathlib import Path
from typing import Optional

import asyncpg

from config import (
    DATABASE_URL,
    MAX_REPORTS_PER_HOUR,
    MIN_VOTES_VERIFIED,
    VERIFIED_RATE_THRESHOLD,
    STALE_RATE_THRESHOLD,
    STALE_DAYS,
    MAX_STRATEGIES_RESPONSE,
    MIN_PROVIDER_STRATEGIES,
    FALLBACK_SUCCESS_RATE,
)

logger = logging.getLogger("crowd.db")

_pool: Optional[asyncpg.Pool] = None


def compute_strategy_hash(zapret_args: list[str]) -> str:
    """Нормализованный SHA-256 хэш аргументов Zapret.

    Сортировка + lower + strip гарантирует, что порядок
    аргументов не влияет на хэш.
    """
    normalized = sorted(arg.strip().lower() for arg in zapret_args if arg.strip())
    return hashlib.sha256("|".join(normalized).encode()).hexdigest()


async def init_pool() -> None:
    """Создаёт пул подключений к PostgreSQL и применяет init.sql."""
    global _pool
    _pool = await asyncpg.create_pool(DATABASE_URL, min_size=2, max_size=10)
    logger.info("DB pool created")

    # Авто-миграция: выполняем init.sql при каждом старте
    init_sql_path = Path(__file__).parent / "init.sql"
    if init_sql_path.exists():
        sql = init_sql_path.read_text(encoding="utf-8")
        async with _pool.acquire() as conn:
            await conn.execute(sql)
        logger.info("init.sql applied successfully")
    else:
        logger.warning("init.sql not found at %s", init_sql_path)


async def close_pool() -> None:
    """Закрывает пул."""
    global _pool
    if _pool is not None:
        await _pool.close()
        _pool = None
        logger.info("DB pool closed")


def _compute_status(success_count: int, fail_count: int) -> str:
    """Вычисляет статус стратегии по формуле из спеки."""
    total = success_count + fail_count
    if total < MIN_VOTES_VERIFIED:
        return "unconfirmed"
    rate = success_count / total
    if rate >= VERIFIED_RATE_THRESHOLD:
        return "verified"
    if rate < STALE_RATE_THRESHOLD:
        return "stale"
    return "unconfirmed"


# ---------------------------------------------------------------
# GET /strategies
# ---------------------------------------------------------------

async def get_strategies(
    provider_id: str,
    service_id: str,
) -> list[dict]:
    """Топ стратегий по провайдеру × сервису с fallback на 'all'."""
    assert _pool is not None

    rows = await _pool.fetch(
        """
        SELECT id, zapret_args, success_count, fail_count,
               avg_latency_ms, status, last_confirmed,
               CASE WHEN (success_count + fail_count) > 0
                    THEN success_count::float / (success_count + fail_count)
                    ELSE 0 END AS success_rate
        FROM strategies
        WHERE provider_id = $1
          AND service_id = $2
          AND status IN ('verified', 'unconfirmed')
        ORDER BY success_rate DESC, last_confirmed DESC
        LIMIT $3
        """,
        provider_id,
        service_id,
        MAX_STRATEGIES_RESPONSE,
    )

    results = [dict(r) for r in rows]

    # Fallback: дополнить из любого провайдера если мало
    if len(results) < MIN_PROVIDER_STRATEGIES:
        existing_hashes = {r["id"] for r in results}
        fallback_rows = await _pool.fetch(
            """
            SELECT id, zapret_args, success_count, fail_count,
                   avg_latency_ms, status, last_confirmed,
                   CASE WHEN (success_count + fail_count) > 0
                        THEN success_count::float / (success_count + fail_count)
                        ELSE 0 END AS success_rate
            FROM strategies
            WHERE service_id = $1
              AND provider_id != $2
              AND status = 'verified'
              AND CASE WHEN (success_count + fail_count) > 0
                       THEN success_count::float / (success_count + fail_count)
                       ELSE 0 END >= $3
            ORDER BY success_rate DESC, last_confirmed DESC
            LIMIT $4
            """,
            service_id,
            provider_id,
            FALLBACK_SUCCESS_RATE,
            MAX_STRATEGIES_RESPONSE - len(results),
        )
        for r in fallback_rows:
            if r["id"] not in existing_hashes:
                results.append(dict(r))

    return results[:MAX_STRATEGIES_RESPONSE]


# ---------------------------------------------------------------
# POST /report
# ---------------------------------------------------------------

async def check_rate_limit(fingerprint: str) -> bool:
    """Проверяет rate limit: <= MAX_REPORTS_PER_HOUR за последний час.

    Returns:
        True если лимит НЕ превышен.
    """
    assert _pool is not None
    count = await _pool.fetchval(
        """
        SELECT COUNT(*) FROM reports
        WHERE fingerprint = $1
          AND reported_at > NOW() - INTERVAL '1 hour'
        """,
        fingerprint,
    )
    return count < MAX_REPORTS_PER_HOUR


async def upsert_strategy(
    provider_id: str,
    service_id: str,
    zapret_args: list[str],
    success: bool,
    latency_ms: float,
    fingerprint: str,
    client_version: str,
) -> tuple[int, str]:
    """UPSERT стратегии + вставка отчёта.

    Returns:
        (strategy_id, strategy_status)
    """
    assert _pool is not None

    strategy_hash = compute_strategy_hash(zapret_args)
    import json
    args_json = json.dumps(zapret_args)

    async with _pool.acquire() as conn:
        async with conn.transaction():
            # UPSERT стратегии
            if success:
                row = await conn.fetchrow(
                    """
                    INSERT INTO strategies
                        (provider_id, service_id, zapret_args, strategy_hash,
                         success_count, fail_count, avg_latency_ms,
                         last_confirmed, first_reported, status)
                    VALUES ($1, $2, $3::jsonb, $4, 1, 0, $5, NOW(), NOW(), 'unconfirmed')
                    ON CONFLICT (provider_id, service_id, strategy_hash)
                    DO UPDATE SET
                        success_count = strategies.success_count + 1,
                        avg_latency_ms = (strategies.avg_latency_ms * strategies.success_count + $5)
                                         / (strategies.success_count + 1),
                        last_confirmed = NOW()
                    RETURNING id, success_count, fail_count
                    """,
                    provider_id,
                    service_id,
                    args_json,
                    strategy_hash,
                    latency_ms,
                )
            else:
                row = await conn.fetchrow(
                    """
                    INSERT INTO strategies
                        (provider_id, service_id, zapret_args, strategy_hash,
                         success_count, fail_count, avg_latency_ms,
                         first_reported, status)
                    VALUES ($1, $2, $3::jsonb, $4, 0, 1, 0, NOW(), 'unconfirmed')
                    ON CONFLICT (provider_id, service_id, strategy_hash)
                    DO UPDATE SET
                        fail_count = strategies.fail_count + 1
                    RETURNING id, success_count, fail_count
                    """,
                    provider_id,
                    service_id,
                    args_json,
                    strategy_hash,
                )

            strategy_id = row["id"]
            new_status = _compute_status(row["success_count"], row["fail_count"])

            # Обновляем статус
            await conn.execute(
                "UPDATE strategies SET status = $1 WHERE id = $2",
                new_status,
                strategy_id,
            )

            # Вставляем отчёт
            await conn.execute(
                """
                INSERT INTO reports
                    (strategy_id, fingerprint, success, latency_ms, client_version)
                VALUES ($1, $2, $3, $4, $5)
                """,
                strategy_id,
                fingerprint,
                success,
                latency_ms,
                client_version,
            )

    return strategy_id, new_status


# ---------------------------------------------------------------
# GET /services
# ---------------------------------------------------------------

async def get_services(provider_id: str) -> list[dict]:
    """Каталог сервисов с количеством стратегий для провайдера."""
    assert _pool is not None

    rows = await _pool.fetch(
        """
        SELECT sc.id, sc.display_name, sc.category, sc.main_domain,
               sc.icon_emoji,
               COALESCE(cnt.strategy_count, 0) AS strategy_count
        FROM services_catalog sc
        LEFT JOIN (
            SELECT service_id, COUNT(*) AS strategy_count
            FROM strategies
            WHERE provider_id = $1
              AND status IN ('verified', 'unconfirmed')
            GROUP BY service_id
        ) cnt ON cnt.service_id = sc.id
        ORDER BY strategy_count DESC, sc.display_name
        """,
        provider_id,
    )
    return [dict(r) for r in rows]


# ---------------------------------------------------------------
# GET /health
# ---------------------------------------------------------------

async def get_health_stats() -> dict:
    """Статистика по стратегиям."""
    assert _pool is not None

    row = await _pool.fetchrow(
        """
        SELECT
            COUNT(*) AS total,
            COUNT(*) FILTER (WHERE status = 'verified') AS verified,
            COUNT(*) FILTER (WHERE status = 'unconfirmed') AS unconfirmed,
            COUNT(*) FILTER (WHERE status = 'degraded') AS degraded,
            COUNT(*) FILTER (WHERE status = 'stale') AS stale
        FROM strategies
        """
    )
    return dict(row)


# ---------------------------------------------------------------
# POST /maintenance/cleanup
# ---------------------------------------------------------------

async def run_cleanup() -> tuple[int, int]:
    """Cron-задача: mark-stale + mark-degraded.

    Returns:
        (stale_marked, degraded_marked)
    """
    assert _pool is not None

    # Mark stale: 7 дней без подтверждений
    stale_result = await _pool.execute(
        """
        UPDATE strategies
        SET status = 'stale'
        WHERE last_confirmed < NOW() - INTERVAL '%s days'
          AND status NOT IN ('stale')
        """ % STALE_DAYS
    )
    stale_count = int(stale_result.split()[-1]) if stale_result else 0

    # Mark degraded: success_rate < 40% среди стратегий с 5+ голосами
    degraded_result = await _pool.execute(
        """
        UPDATE strategies
        SET status = 'degraded'
        WHERE (success_count + fail_count) >= $1
          AND success_count::float / (success_count + fail_count) < $2
          AND status NOT IN ('stale', 'degraded')
        """,
        MIN_VOTES_VERIFIED,
        STALE_RATE_THRESHOLD,
    )
    degraded_count = int(degraded_result.split()[-1]) if degraded_result else 0

    logger.info("Cleanup: stale=%d, degraded=%d", stale_count, degraded_count)
    return stale_count, degraded_count
