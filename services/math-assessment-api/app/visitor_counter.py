"""Privacy-preserving public visit counters backed by a durable remote counter."""

from __future__ import annotations

import json
import os
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from typing import Final
from urllib.parse import quote
from urllib.request import Request, urlopen

COUNTER_BASE: Final = "https://countapi.mileshilliard.com/api/v1"
KOREA_TIMEZONE: Final = timezone(timedelta(hours=9))


def korea_date() -> str:
    return datetime.now(KOREA_TIMEZONE).strftime("%Y-%m-%d")


def _counter_value(key: str, *, increment: bool) -> int | None:
    # The previous provider's aggregate read endpoint ignored the requested
    # key, so today's count and the lifetime count became identical.  This
    # provider exposes separate read-only (`get`) and increment (`hit`)
    # endpoints for one exact public key.
    action = "hit" if increment else "get"
    path = "/".join(quote(part, safe="") for part in (action, key))
    request = Request(
        f"{COUNTER_BASE}/{path}",
        headers={"Accept": "application/json", "User-Agent": "suhaeng-math/0.3"},
    )
    try:
        with urlopen(request, timeout=4) as response:  # noqa: S310 - fixed HTTPS origin
            payload = json.loads(response.read().decode("utf-8"))
    except (OSError, TimeoutError, ValueError, json.JSONDecodeError):
        return None
    value = payload.get("value") if isinstance(payload, dict) else None
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return None
    return parsed if parsed >= 0 else None


def _counter_state(key: str, *, increment: bool) -> tuple[int | None, bool]:
    """Record at most one visit, or read the exact shared counter."""

    value = _counter_value(key, increment=increment)
    return value, increment and value is not None


def visitor_counts(*, increment_today: bool, increment_total: bool) -> dict[str, object]:
    date = korea_date()
    namespace = os.environ.get("MATH_ASSESSMENT_COUNTER_NAMESPACE", "").strip()
    if not namespace:
        return {
            "date": date,
            "today": None,
            "total": None,
            "today_incremented": False,
            "total_incremented": False,
            "available": False,
        }
    with ThreadPoolExecutor(max_workers=2) as executor:
        today_future = executor.submit(
            _counter_state,
            f"{namespace}_day_{date.replace('-', '')}",
            increment=increment_today,
        )
        total_future = executor.submit(
            _counter_state,
            f"{namespace}_total",
            increment=increment_total,
        )
        today, today_incremented = today_future.result()
        total, total_incremented = total_future.result()
    return {
        "date": date,
        "today": today,
        "total": total,
        "today_incremented": today_incremented,
        "total_incremented": total_incremented,
        "available": today is not None and total is not None,
    }
