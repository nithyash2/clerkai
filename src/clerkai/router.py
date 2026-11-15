"""Business rules that turn an extraction into a decision.

The LLM reads documents; plain, testable rules decide what happens next.
Keeping decisions out of the LLM makes them predictable and auditable.
"""

from __future__ import annotations

import re
from datetime import date

from .payments import PaymentCheck
from .schemas import Decision, DocType, Extraction, Priority

REVIEW_CONFIDENCE = 0.75  # below this, a person checks the extraction
HIGH_VALUE_AUD = 10_000  # amounts at or above this always get a second look
DUE_SOON_DAYS = 7

ROUTES: dict[DocType, tuple[str, str]] = {
    DocType.INVOICE: ("Bookkeeping", "record_invoice"),
    DocType.RECEIPT: ("Bookkeeping", "record_receipt"),
    DocType.ATO_NOTICE: ("Tax", "create_task"),
    DocType.CLIENT_QUERY: ("Client Services", "draft_reply"),
    DocType.OTHER: ("Triage", "manual_review"),
}


_BANK_CHANGE = re.compile(
    r"(?is)\b(update|change|new|replace)\b.{0,60}\b(bank|refund|payment|account)\s+(details|account)"
)


def risk_flags(original_text: str) -> list[str]:
    """Patterns that need a person no matter how confident the AI is."""
    flags = []
    if _BANK_CHANGE.search(original_text):
        flags.append("bank detail change request: verify by phone before acting (common fraud pattern)")
    return flags


def decide(
    ex: Extraction,
    today: date,
    flags: list[str] | None = None,
    payment: PaymentCheck | None = None,
) -> Decision:
    team, action = ROUTES[ex.doc_type]
    priority = Priority.NORMAL
    reasons: list[str] = []
    needs_review = False

    if ex.due_date is not None:
        days_left = (ex.due_date - today).days
        if days_left < 0:
            priority = Priority.URGENT
            reasons.append(f"overdue by {-days_left} days")
        elif days_left <= DUE_SOON_DAYS:
            priority = Priority.HIGH
            reasons.append(f"due in {days_left} days")

    if ex.doc_type is DocType.ATO_NOTICE:
        needs_review = True
        priority = max(priority, Priority.HIGH, key=_rank)
        reasons.append("ATO correspondence is always reviewed by a person")

    if ex.doc_type is DocType.RECEIPT and priority is Priority.NORMAL:
        priority = Priority.LOW

    if ex.doc_type is DocType.OTHER:
        needs_review = True
        reasons.append("document type not recognised")

    if ex.confidence < REVIEW_CONFIDENCE:
        needs_review = True
        reasons.append(f"low confidence ({ex.confidence:.2f})")

    if ex.amount is not None and ex.amount >= HIGH_VALUE_AUD:
        needs_review = True
        reasons.append(f"high value (${ex.amount:,.2f})")

    for flag in flags or []:
        needs_review = True
        priority = max(priority, Priority.HIGH, key=_rank)
        reasons.append(flag)

    hold, tasks = False, []
    if payment is not None and payment.status == "mismatch":
        hold, needs_review, action = True, True, "hold_payment"
        priority = Priority.URGENT
        reasons.append(payment.reason or "bank details differ from the record on file")
        tasks.append(payment.task or "Verify the bank details by phone before paying.")
    elif payment is not None and payment.status == "unknown_supplier":
        needs_review = True
        priority = max(priority, Priority.HIGH, key=_rank)
        reasons.append(payment.reason or "payment details from an unknown supplier")
        tasks.append(payment.task or "Verify the supplier before paying.")
    elif payment is not None and payment.status == "match":
        reasons.append(payment.reason or "bank details match the record on file")

    return Decision(
        team=team, action=action, priority=priority, needs_review=needs_review,
        hold=hold, reasons=reasons, tasks=tasks,
    )


def failed_decision(error: str) -> Decision:
    """When extraction fails, a person handles the document. Nothing is dropped."""
    return Decision(
        team="Triage",
        action="manual_review",
        priority=Priority.HIGH,
        needs_review=True,
        reasons=[f"automatic extraction failed: {error}"],
    )


_ORDER = [Priority.LOW, Priority.NORMAL, Priority.HIGH, Priority.URGENT]


def _rank(p: Priority) -> int:
    return _ORDER.index(p)
