"""Data models shared across ClerkAI.

Every LLM output is validated against these models before it is used, so a
malformed or nonsensical answer is caught instead of flowing downstream.
"""

from __future__ import annotations

from datetime import date
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field, model_validator


class DocType(str, Enum):
    INVOICE = "invoice"
    RECEIPT = "receipt"
    ATO_NOTICE = "ato_notice"
    CLIENT_QUERY = "client_query"
    OTHER = "other"


class Extraction(BaseModel):
    """Structured fields pulled out of one inbox document."""

    doc_type: DocType
    client_name: str | None = None
    amount: float | None = Field(default=None, ge=0, description="Total amount in AUD")
    gst: float | None = Field(default=None, ge=0, description="GST component in AUD")
    due_date: date | None = None
    reference: str | None = Field(default=None, description="Invoice number or notice reference")
    summary: str = Field(max_length=300)
    confidence: float = Field(ge=0, le=1, description="Model's confidence in the extraction")

    @model_validator(mode="after")
    def gst_not_more_than_total(self) -> Extraction:
        if self.amount is not None and self.gst is not None and self.gst > self.amount:
            raise ValueError("gst cannot be larger than the total amount")
        return self


class Priority(str, Enum):
    LOW = "low"
    NORMAL = "normal"
    HIGH = "high"
    URGENT = "urgent"


class Decision(BaseModel):
    """What ClerkAI decides to do with a document."""

    team: str
    action: str
    priority: Priority
    needs_review: bool
    hold: bool = False  # payment must not be made until a person verifies it
    reasons: list[str] = Field(default_factory=list)
    tasks: list[str] = Field(default_factory=list)  # follow-up actions for a person


class RunResult(BaseModel):
    """The full outcome of processing one document, as logged."""

    run_id: int | None = None
    source: str
    status: str  # "ok" or "failed"
    extraction: Extraction | None = None
    decision: Decision
    pii_masked: dict[str, int] = Field(default_factory=dict)
    latency_ms: float
    attempts: int
    llm: str
    error: str | None = None
    draft: dict[str, Any] | None = None  # agent-drafted reply, awaiting human approval
