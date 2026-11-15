"""PII guardrail: mask sensitive numbers before any text reaches the LLM.

Instead of masking every long number (which would also hide invoice numbers),
each candidate is checked with the real validation algorithm for its type:
  - Tax File Numbers use the ATO weighted checksum (mod 11).
  - Card numbers use the Luhn checksum.
  - BSB and account numbers are masked when labelled as such.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

TFN_WEIGHTS = (1, 4, 3, 7, 5, 8, 6, 9, 10)

# The extra look-arounds stop a TFN match inside a longer grouped number such as an
# ABN ("33 102 417 032"), whose last 9 digits can pass the TFN checksum by chance.
_TFN_CANDIDATE = re.compile(r"(?<!\d)(?<!\d[ -])(\d{3})[ -]?(\d{3})[ -]?(\d{3})(?![ -]?\d)")
_CARD_CANDIDATE = re.compile(r"(?<!\d)(?:\d[ -]?){13,19}(?!\d)")
_BSB = re.compile(r"(?i)(\bBSB\b\D{0,5})(\d{3}[ -]?\d{3})")
_ACCOUNT = re.compile(r"(?i)(\b(?:account|acct|a/c)\s*(?:no\.?|number|#)?\s*:?\s*)(\d{6,10})\b")


def is_valid_tfn(digits: str) -> bool:
    """ATO checksum: weighted sum of the 9 digits must divide evenly by 11."""
    if len(digits) != 9 or not digits.isdigit():
        return False
    return sum(int(d) * w for d, w in zip(digits, TFN_WEIGHTS)) % 11 == 0


def is_valid_luhn(digits: str) -> bool:
    """Luhn checksum used by payment cards."""
    if not 13 <= len(digits) <= 19 or not digits.isdigit():
        return False
    total = 0
    for i, ch in enumerate(reversed(digits)):
        n = int(ch)
        if i % 2 == 1:
            n *= 2
            if n > 9:
                n -= 9
        total += n
    return total % 10 == 0


@dataclass
class MaskResult:
    text: str
    counts: dict[str, int] = field(default_factory=dict)

    @property
    def total(self) -> int:
        return sum(self.counts.values())


def mask_pii(text: str) -> MaskResult:
    counts: dict[str, int] = {}

    def bump(kind: str) -> None:
        counts[kind] = counts.get(kind, 0) + 1

    def card_sub(m: re.Match[str]) -> str:
        digits = re.sub(r"\D", "", m.group(0))
        if is_valid_luhn(digits):
            bump("card")
            return "[CARD]"
        return m.group(0)

    def bsb_sub(m: re.Match[str]) -> str:
        bump("bsb")
        return f"{m.group(1)}[BSB]"

    def account_sub(m: re.Match[str]) -> str:
        bump("account")
        return f"{m.group(1)}[ACCOUNT]"

    def tfn_sub(m: re.Match[str]) -> str:
        if is_valid_tfn("".join(m.groups())):
            bump("tfn")
            return "[TFN]"
        return m.group(0)

    # Order matters: longer card numbers first, then labelled bank details, then TFNs.
    text = _CARD_CANDIDATE.sub(card_sub, text)
    text = _BSB.sub(bsb_sub, text)
    text = _ACCOUNT.sub(account_sub, text)
    text = _TFN_CANDIDATE.sub(tfn_sub, text)
    return MaskResult(text=text, counts=counts)
