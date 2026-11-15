"""Payment redirection check: compare bank details in a document with the supplier's record.

Fake invoices and "we've changed banks" emails are a common scam (the ACCC's advice:
verify new bank details by calling the supplier on a number you already have). A keyword
check misses an invoice that silently carries a different account, so ClerkAI compares the
BSB and account number in the document with the supplier record on file.

This runs on the ORIGINAL text, locally, before masking: the bank numbers are never sent
to the LLM, and reasons only show the last three digits so the run log stays safe.
"""

from __future__ import annotations

import json
import re
from typing import Literal

from pydantic import BaseModel, Field

from .masking import _ACCOUNT, _BSB
from .tools import DATA_DIR

_ABN = re.compile(r"(?i)\bABN\b\D{0,5}(\d{2}\s?\d{3}\s?\d{3}\s?\d{3})")

Status = Literal["none", "match", "mismatch", "unknown_supplier"]


class PaymentCheck(BaseModel):
    status: Status = "none"
    supplier: str | None = None
    reason: str | None = None
    task: str | None = None
    changed: list[str] = Field(default_factory=list)  # "bsb", "account"


def _digits(s: str) -> str:
    return re.sub(r"\D", "", s)


def _suppliers() -> list[dict[str, str]]:
    path = DATA_DIR / "suppliers.json"
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else []


def find_supplier(text: str) -> dict[str, str] | None:
    """Match by ABN first (unique and hard to get wrong), then by name or alias."""
    suppliers = _suppliers()
    for m in _ABN.finditer(text):
        for s in suppliers:
            if _digits(s["abn"]) == _digits(m.group(1)):
                return s
    lowered = text.lower()
    for s in suppliers:
        if any(n.lower() in lowered for n in [s["name"], *s.get("aliases", [])] if n):
            return s
    return None


def bank_details(text: str) -> tuple[str | None, str | None]:
    bsb = _BSB.search(text)
    acct = _ACCOUNT.search(text)
    return (_digits(bsb.group(2)) if bsb else None, _digits(acct.group(2)) if acct else None)


def _tail(digits: str) -> str:
    return f"ending {digits[-3:]}"


def check_payment_details(text: str, is_invoice: bool) -> PaymentCheck:
    bsb, account = bank_details(text)
    if not (bsb or account):
        return PaymentCheck()

    supplier = find_supplier(text)
    if supplier is None:
        if not is_invoice:
            return PaymentCheck()  # e.g. a client's own refund details: handled by risk_flags
        return PaymentCheck(
            status="unknown_supplier",
            reason="payment details from a supplier not on file: verify before the first payment",
            task="Confirm the supplier's identity and bank details through an independent "
            "source (not the contact details in this document) before paying.",
        )

    changed = []
    if bsb and bsb != _digits(supplier["bsb"]):
        changed.append("bsb")
    if account and account != _digits(supplier["account"]):
        changed.append("account")
    name = supplier["name"]
    if not changed:
        return PaymentCheck(status="match", supplier=name,
                            reason=f"bank details match the record on file for {name}")

    parts = []
    if "bsb" in changed:
        parts.append(f"BSB {_tail(bsb)} (on file: {_tail(_digits(supplier['bsb']))})")
    if "account" in changed:
        parts.append(f"account {_tail(account)} (on file: {_tail(_digits(supplier['account']))})")
    return PaymentCheck(
        status="mismatch",
        supplier=name,
        changed=changed,
        reason=f"PAYMENT HOLD: bank details differ from the record for {name}: " + ", ".join(parts),
        task=f"Do not pay. Call {name} on {supplier['phone']} (the number on file, not one in "
        "this document) to confirm the new details, then update the supplier record.",
    )
