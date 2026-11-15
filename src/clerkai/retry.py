"""Retry temporary LLM failures (busy servers, rate limits) with exponential backoff.

Permanent errors such as a wrong model name or an invalid key are not retried:
waiting would not fix them, so the document goes to manual review straight away.
"""

from __future__ import annotations

import random
import sys
import time
from collections.abc import Callable
from typing import TypeVar

T = TypeVar("T")

TRANSIENT_MARKERS = (
    "429", "500", "502", "503", "504",
    "UNAVAILABLE", "RESOURCE_EXHAUSTED", "DEADLINE_EXCEEDED", "INTERNAL",
    "timed out", "timeout", "connection",
)
DELAYS_SECONDS = (2.0, 4.0, 8.0)  # three retries: about 14 seconds in the worst case


def is_transient(exc: Exception) -> bool:
    text = f"{type(exc).__name__} {exc}"
    return any(marker.lower() in text.lower() for marker in TRANSIENT_MARKERS)


def with_retries(
    fn: Callable[[], T],
    delays: tuple[float, ...] = DELAYS_SECONDS,
    sleep: Callable[[float], None] = time.sleep,
) -> tuple[T, int]:
    """Run fn; on a transient error wait and try again. Returns (result, retries used)."""
    for retries, delay in enumerate((*delays, None)):
        try:
            return fn(), retries
        except Exception as exc:
            if delay is None or not is_transient(exc):
                raise
            wait = delay + random.uniform(0, 0.5)  # jitter avoids many clients retrying in sync
            print(f"  AI service busy, retrying in {wait:.0f}s ({retries + 1}/{len(delays)})", file=sys.stderr)
            sleep(wait)
    raise RuntimeError("unreachable")
