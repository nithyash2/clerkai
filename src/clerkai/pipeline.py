"""The end-to-end flow for one document:

    mask PII -> LLM extraction -> validate (retry once with the error) -> decide -> log

Two kinds of retry are kept separate:
  - temporary service errors (busy model, rate limit) wait and try again (retry.py);
  - invalid output is sent back to the model with its validation error.
"""

from __future__ import annotations

import json
import re
import time
from collections.abc import Callable
from datetime import date

from pydantic import ValidationError

from .llm import LLMClient
from .masking import mask_pii
from .agent import draft_reply
from .retry import with_retries
from .entities import match_entity
from .payments import check_payment_details
from .router import decide, failed_decision, risk_flags
from .schemas import DocType, Extraction, RunResult
from .store import RunStore

MAX_ATTEMPTS = 2


def _parse(raw: str) -> Extraction:
    """Strip markdown fences if a model adds them, then validate strictly."""
    cleaned = re.sub(r"^```(?:json)?\s*|\s*```$", "", raw.strip())
    return Extraction.model_validate(json.loads(cleaned))


def process_document(
    text: str,
    source: str,
    client: LLMClient,
    store: RunStore | None = None,
    today: date | None = None,
    draft_replies: bool = True,
    sleep: Callable[[float], None] = time.sleep,
) -> RunResult:
    today = today or date.today()
    start = time.perf_counter()

    masked = mask_pii(text)
    extraction: Extraction | None = None
    feedback: str | None = None
    error: str | None = None
    attempts = 0
    service_retries = 0

    for attempts in range(1, MAX_ATTEMPTS + 1):
        try:
            raw, used = with_retries(lambda: client.extract(masked.text, feedback), sleep=sleep)
            service_retries += used
            extraction = _parse(raw)
            error = None
            break
        except (json.JSONDecodeError, ValidationError) as exc:
            # Give the model its own validation error and ask it to fix the answer.
            feedback = str(exc)[:500]
            error = f"invalid output: {type(exc).__name__}"
        except Exception as exc:  # network errors, quota limits, etc.
            error = f"llm error: {type(exc).__name__}: {exc}"[:300]
            break

    flags = risk_flags(text)
    if extraction:
        # Runs on the original text, locally: bank numbers never go to the LLM.
        is_invoice = extraction.doc_type is DocType.INVOICE
        payment = check_payment_details(text, is_invoice)
        entity = match_entity(text, extraction.client_name)
        decision = decide(extraction, today, flags, payment, entity)
    else:
        decision = failed_decision(error or "unknown")

    draft = None
    if extraction and extraction.doc_type is DocType.CLIENT_QUERY and draft_replies:
        try:
            reply, used = with_retries(lambda: draft_reply(masked.text, extraction, client), sleep=sleep)
            service_retries += used
            draft = reply.model_dump()
        except Exception as exc:  # a failed draft never blocks triage
            decision.reasons.append(f"reply draft failed: {type(exc).__name__}")
    if service_retries:
        decision.reasons.append(f"recovered from {service_retries} temporary AI service error(s)")
    if masked.total:
        decision.reasons.append(f"masked {masked.total} sensitive value(s) before AI processing")

    result = RunResult(
        source=source,
        status="ok" if extraction else "failed",
        extraction=extraction,
        decision=decision,
        pii_masked=masked.counts,
        latency_ms=round((time.perf_counter() - start) * 1000, 1),
        attempts=attempts,
        llm=client.name,
        error=None if extraction else error,
        draft=draft,
    )
    if store is not None:
        result.run_id = store.log(result)
    return result
