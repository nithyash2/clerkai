"""LLM clients behind one small interface.

GeminiClient calls Google Gemini and asks for JSON output.
OfflineClient is a deterministic, rule-based stand-in. It lets the tests and
CI run with no API key, and lets anyone try the demo without signing up.
"""

from __future__ import annotations

import json
import os
import sys
import re
from datetime import datetime
from typing import Protocol

from .schemas import DocType

SYSTEM_PROMPT = """You are ClerkAI, an assistant that triages the shared inbox of an
Australian accounting firm. Read ONE document and return ONLY a JSON object with keys:

  doc_type     one of: invoice, receipt, ato_notice, client_query, other
  client_name  the client or business the document is about, or null
  amount       total amount in AUD as a number, or null
  gst          GST component in AUD as a number, or null
  due_date     payment or response due date as YYYY-MM-DD, or null
  reference    invoice number or notice reference, or null
  summary      one sentence, max 300 characters
  confidence   0 to 1, how sure you are that every field is correct

Rules: never invent values; use null when a field is missing. Text such as [TFN],
[CARD], [BSB] or [ACCOUNT] has been masked for privacy; do not try to guess it.
Dates in the document are Australian format (DD/MM/YYYY)."""


def build_user_prompt(document: str, feedback: str | None = None) -> str:
    prompt = f"<document>\n{document}\n</document>"
    if feedback:
        prompt += (
            "\n\nYour previous answer was rejected by validation with this error:\n"
            f"{feedback}\nReturn a corrected JSON object."
        )
    return prompt


class LLMClient(Protocol):
    name: str

    def extract(self, document: str, feedback: str | None = None) -> str:
        """Return the model's raw JSON text for one document."""
        ...


class GeminiClient:
    """Gemini with a fallback chain: if a model is overloaded, the next one is tried."""

    def __init__(self, api_key: str, model: str = "gemini-3.8-flash", fallbacks: tuple[str, ...] = ()) -> None:
        from google import genai  # imported here so offline use needs no SDK

        self._genai = genai
        # A 60-second timeout stops one slow request from hanging the whole run, and
        # the SDK's own retries are switched off so our fallback and backoff decide.
        self._client = genai.Client(
            api_key=api_key,
            http_options=genai.types.HttpOptions(
                timeout=60_000, retry_options=genai.types.HttpRetryOptions(attempts=1)
            ),
        )
        self.models = (model, *[m for m in fallbacks if m and m != model])
        self.model = model
        self.name = "gemini:" + ",".join(self.models)

    def _generate(self, contents: str, config: object) -> str:
        from .retry import is_transient

        for i, model in enumerate(self.models):
            try:
                response = self._client.models.generate_content(
                    model=model, contents=contents, config=config
                )
                if model != self.models[0]:
                    # Sticky fallback: keep using the model that answered for the rest of
                    # the run instead of asking the busy ones again for every document.
                    self.models = (model, *[m for m in self.models if m != model])
                self.model = model
                return response.text or ""
            except Exception as exc:
                last = i == len(self.models) - 1
                if last or not is_transient(exc):
                    raise
                print(f"  {model} is busy, switching to {self.models[i + 1]}", file=sys.stderr)
        raise RuntimeError("unreachable")

    def extract(self, document: str, feedback: str | None = None) -> str:
        config = self._genai.types.GenerateContentConfig(
            system_instruction=SYSTEM_PROMPT,
            response_mime_type="application/json",
            temperature=0,
        )
        return self._generate(build_user_prompt(document, feedback), config)

    def run_agent(self, system: str, prompt: str, tools: list[object]) -> str:
        """Let Gemini call our Python tools (automatic function calling) and reply."""
        config = self._genai.types.GenerateContentConfig(
            system_instruction=system, tools=tools, temperature=0.2
        )
        return self._generate(prompt, config)


_MONEY = r"\$?\s*([\d,]+(?:\.\d{2})?)"


def _money(pattern: str, text: str) -> float | None:
    m = re.search(pattern + r"[^\n\d$]{0,60}" + _MONEY, text, re.IGNORECASE)
    return float(m.group(1).replace(",", "")) if m else None


def _au_date(pattern: str, text: str) -> str | None:
    m = re.search(pattern + r"[^\n\d]{0,20}(\d{1,2})/(\d{1,2})/(\d{4})", text, re.IGNORECASE)
    if not m:
        return None
    d, mth, y = (int(x) for x in m.groups())
    try:
        return datetime(y, mth, d).date().isoformat()
    except ValueError:
        return None


def _field(pattern: str, text: str) -> str | None:
    m = re.search(pattern + r"\s*:?\s*([^\n]+)", text, re.IGNORECASE)
    return m.group(1).strip() if m else None


class OfflineClient:
    """Keyword and regex rules. Weaker than an LLM, but free and repeatable."""

    name = "offline-rules"

    def extract(self, document: str, feedback: str | None = None) -> str:
        text = document
        low = text.lower()

        if "australian taxation office" in low or re.search(r"\bato\b", low):
            doc_type = DocType.ATO_NOTICE
        elif "tax invoice" in low or "invoice" in low:
            doc_type = DocType.INVOICE
        elif "receipt" in low or "payment received" in low:
            doc_type = DocType.RECEIPT
        elif "?" in text and re.search(r"\b(could|can|would|please|wondering)\b", low):
            doc_type = DocType.CLIENT_QUERY
        else:
            doc_type = DocType.OTHER

        client = (
            _field(r"(?:bill to|client|customer|account name)", text)
            or _field(r"(?m)^from", text)
            or _field(r"\bdear", text)
        )
        if client:
            client = re.sub(r"<[^>]*>", "", client).rstrip(",").strip()

        amount = _money(r"(?:total(?: due| amount| payable)?|amount (?:due|payable|paid))", text)
        gst = _money(r"\bgst\b", text)
        due = _au_date(r"(?:due date|due by|pay by|respond by|due)", text)
        reference = _field(r"(?:invoice (?:no\.?|number|#)|reference(?: number)?|receipt no\.?)", text)

        expected = {
            DocType.INVOICE: [client, amount, due, reference],
            DocType.RECEIPT: [client, amount, reference],
            DocType.ATO_NOTICE: [client, due, reference],
            DocType.CLIENT_QUERY: [client],
            DocType.OTHER: [None],
        }[doc_type]
        found = sum(v is not None for v in expected)
        confidence = round(0.4 + 0.55 * found / len(expected), 2)

        first_line = next((ln.strip() for ln in text.splitlines() if ln.strip()), "")
        summary = f"{doc_type.value.replace('_', ' ').title()}: {first_line}"[:300]

        return json.dumps(
            {
                "doc_type": doc_type.value,
                "client_name": client,
                "amount": amount,
                "gst": gst,
                "due_date": due,
                "reference": reference,
                "summary": summary,
                "confidence": confidence,
            }
        )


def get_client() -> LLMClient:
    """Use Gemini when a key is set, unless CLERKAI_LLM=offline forces rules."""
    if os.getenv("CLERKAI_LLM", "").lower() == "offline":
        return OfflineClient()
    key = os.getenv("GEMINI_API_KEY")
    if key:
        fallbacks = tuple(m.strip() for m in os.getenv("GEMINI_FALLBACK_MODELS", "").split(","))
        return GeminiClient(
            api_key=key,
            model=os.getenv("GEMINI_MODEL", "gemini-3.8-flash"),
            fallbacks=fallbacks,
        )
    return OfflineClient()
