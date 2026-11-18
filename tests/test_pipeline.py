import json
from datetime import date
from pathlib import Path

import pytest
from pydantic import ValidationError

from clerkai.llm import OfflineClient
from clerkai.pipeline import process_document
from clerkai.schemas import Extraction
from clerkai.store import RunStore

SAMPLES = Path(__file__).parent.parent / "samples"
TODAY = date(2026, 11, 10)
GOOD = json.dumps(
    {"doc_type": "receipt", "client_name": "X", "amount": 10.0, "gst": 1.0,
     "due_date": None, "reference": "R1", "summary": "ok", "confidence": 0.9}
)


class ScriptedClient:
    """Returns pre-set answers and records exactly what it was sent."""

    name = "scripted"

    def __init__(self, *answers):
        self.answers = list(answers)
        self.seen = []

    def extract(self, document, feedback=None):
        self.seen.append((document, feedback))
        return self.answers.pop(0)


def test_pii_never_reaches_the_llm():
    spy = ScriptedClient(GOOD)
    process_document("TFN 123 456 782, card 4111 1111 1111 1111", "t", spy, today=TODAY)
    sent = spy.seen[0][0]
    assert "123 456 782" not in sent and "4111" not in sent


def test_invalid_output_is_retried_with_the_error():
    spy = ScriptedClient("not json at all", GOOD)
    r = process_document("receipt", "t", spy, today=TODAY)
    assert r.status == "ok" and r.attempts == 2
    assert spy.seen[1][1] is not None  # second call carried the validation error


def test_repeated_failure_goes_to_manual_review():
    r = process_document("x", "t", ScriptedClient("{}", "{}"), today=TODAY)
    assert r.status == "failed" and r.decision.needs_review
    assert r.decision.action == "manual_review"


def test_schema_rejects_gst_larger_than_total():
    with pytest.raises(ValidationError):
        Extraction(doc_type="invoice", amount=10, gst=50, summary="s", confidence=0.9)


@pytest.mark.parametrize(
    "file, doc_type",
    [
        ("01_invoice_overdue.txt", "invoice"),
        ("02_invoice_high_value.txt", "invoice"),
        ("03_receipt.txt", "receipt"),
        ("04_ato_notice.txt", "ato_notice"),
        ("05_client_query.txt", "client_query"),
        ("06_unclear.txt", "other"),
    ],
)
def test_offline_client_classifies_samples(file, doc_type):
    r = process_document((SAMPLES / file).read_text(), file, OfflineClient(), today=TODAY)
    assert r.extraction.doc_type.value == doc_type


def test_runs_are_logged_for_monitoring(tmp_path):
    store = RunStore(tmp_path / "runs.db")
    for f in sorted(SAMPLES.glob("*.txt")):
        process_document(f.read_text(), f.name, OfflineClient(), store, today=TODAY)
    s = store.stats()
    assert s["runs"] == 6 and s["pii_masked"] >= 4
    assert len(store.review_queue()) >= 3


class FlakyClient:
    """Fails with a busy-server error a set number of times, then answers."""

    name = "flaky"

    def __init__(self, failures, error="503 UNAVAILABLE: model is experiencing high demand"):
        self.failures, self.error, self.calls = failures, error, 0

    def extract(self, document, feedback=None):
        self.calls += 1
        if self.calls <= self.failures:
            raise RuntimeError(self.error)
        return GOOD


def test_busy_model_is_retried_then_succeeds():
    waits = []
    r = process_document("receipt", "t", FlakyClient(2), today=TODAY, sleep=waits.append)
    assert r.status == "ok" and len(waits) == 2
    assert any("recovered from 2 temporary" in x for x in r.decision.reasons)


def test_permanent_error_is_not_retried():
    waits = []
    client = FlakyClient(5, error="404 NOT_FOUND: model is no longer available")
    r = process_document("receipt", "t", client, today=TODAY, sleep=waits.append)
    assert r.status == "failed" and waits == [] and client.calls == 1


def test_gives_up_after_three_retries():
    waits = []
    r = process_document("receipt", "t", FlakyClient(10), today=TODAY, sleep=waits.append)
    assert r.status == "failed" and len(waits) == 3 and r.decision.needs_review


def test_busy_model_falls_back_to_next_model():
    from clerkai.llm import GeminiClient

    class FakeModels:
        def __init__(self):
            self.tried = []

        def generate_content(self, model, contents, config):
            self.tried.append(model)
            if model == "main":
                raise RuntimeError("503 UNAVAILABLE: high demand")
            return type("R", (), {"text": GOOD})()

    client = GeminiClient.__new__(GeminiClient)
    client._client = type("C", (), {"models": FakeModels()})()
    client.models, client.model = ("main", "backup"), "main"
    assert client._generate("doc", None) == GOOD
    assert client._client.models.tried == ["main", "backup"] and client.model == "backup"
    # the working model is now tried first
    assert client._generate("doc", None) == GOOD
    assert client._client.models.tried == ["main", "backup", "backup"]


@pytest.mark.parametrize(
    "text, expected",
    [
        ("TAX INVOICE / RECEIPT\nTotal $99.00\nPaid by EFTPOS", "receipt"),
        ("Tax Invoice\nTotal $267.00\nAmount paid: $267.00  Balance owing: $0.00", "receipt"),
        ("TAX INVOICE\nTotal due $825.00\nDue date: 20/11/2026", "invoice"),
        ("TAX INVOICE\nTotal $500.00\nTo be paid by 30/11/2026", "invoice"),
    ],
)
def test_paid_tax_invoices_are_receipts_but_unpaid_ones_are_invoices(text, expected):
    r = process_document(text, "t", OfflineClient(), today=TODAY, draft_replies=False)
    assert r.extraction.doc_type.value == expected
