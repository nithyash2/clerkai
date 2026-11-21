"""Token and cost tracking for every LLM call.

Each call records the model and the input/output tokens Gemini reports. The pipeline
collects them per document, so the run log shows tokens and cost for every run and
the monitoring screen can answer "what does this cost per 1,000 documents?".

Prices change and differ by model, so they are configuration, not code: set
CLERKAI_PRICE_IN_PER_M and CLERKAI_PRICE_OUT_PER_M (USD per million tokens) from the
provider's pricing page. Without them, tokens are still tracked and cost shows as unknown.
"""

from __future__ import annotations

import os
import threading
from dataclasses import dataclass


@dataclass
class Usage:
    model: str
    tokens_in: int
    tokens_out: int


_local = threading.local()  # one log per thread, so concurrent API requests don't mix


def record(model: str, response: object) -> None:
    meta = getattr(response, "usage_metadata", None)
    if meta is None:
        return
    entry = Usage(model, int(getattr(meta, "prompt_token_count", 0) or 0),
                  int(getattr(meta, "candidates_token_count", 0) or 0))
    _log().append(entry)


def _log() -> list[Usage]:
    if not hasattr(_local, "entries"):
        _local.entries = []
    return _local.entries


def take() -> list[Usage]:
    """Return and clear the calls recorded on this thread since the last take()."""
    entries = list(_log())
    _log().clear()
    return entries


def prices() -> tuple[float, float] | None:
    try:
        return float(os.environ["CLERKAI_PRICE_IN_PER_M"]), float(os.environ["CLERKAI_PRICE_OUT_PER_M"])
    except (KeyError, ValueError):
        return None


def cost_usd(tokens_in: int, tokens_out: int) -> float | None:
    p = prices()
    if p is None:
        return None
    return round(tokens_in / 1e6 * p[0] + tokens_out / 1e6 * p[1], 6)
