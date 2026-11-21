from datetime import date
from types import SimpleNamespace

from clerkai import usage
from clerkai.llm import GeminiClient
from clerkai.pipeline import process_document
from clerkai.store import RunStore

GOOD = ('{"doc_type": "receipt", "client_name": "X", "amount": 10.0, "gst": 1.0, '
        '"due_date": null, "reference": "R1", "summary": "ok", "confidence": 0.9}')


def fake_gemini(tokens_in=1200, tokens_out=80):
    class Models:
        def generate_content(self, model, contents, config):
            meta = SimpleNamespace(prompt_token_count=tokens_in, candidates_token_count=tokens_out)
            return SimpleNamespace(text=GOOD, usage_metadata=meta)

    client = GeminiClient.__new__(GeminiClient)
    client._client = SimpleNamespace(models=Models())
    client.models, client.model, client.name = ("m",), "m", "gemini:m"
    client._genai = SimpleNamespace(types=SimpleNamespace(GenerateContentConfig=lambda **k: None))
    return client


def test_tokens_are_recorded_per_document(monkeypatch):
    monkeypatch.delenv("CLERKAI_PRICE_IN_PER_M", raising=False)
    r = process_document("receipt", "t", fake_gemini(), today=date(2026, 11, 10))
    assert (r.llm_calls, r.tokens_in, r.tokens_out) == (1, 1200, 80)
    assert r.cost_usd is None  # no prices configured: unknown, not zero


def test_cost_uses_configured_prices(monkeypatch):
    monkeypatch.setenv("CLERKAI_PRICE_IN_PER_M", "0.50")
    monkeypatch.setenv("CLERKAI_PRICE_OUT_PER_M", "2.00")
    r = process_document("receipt", "t", fake_gemini(1_000_000, 500_000), today=date(2026, 11, 10))
    assert r.cost_usd == 1.5


def test_usage_does_not_leak_between_documents():
    process_document("receipt", "t", fake_gemini(), today=date(2026, 11, 10))
    assert usage.take() == []


def test_run_log_stores_tokens_and_old_databases_are_upgraded(tmp_path):
    import sqlite3

    path = tmp_path / "old.db"
    old = sqlite3.connect(path)
    old.execute("CREATE TABLE runs (id INTEGER PRIMARY KEY, created_at TEXT NOT NULL, source TEXT NOT NULL,"
                " llm TEXT NOT NULL, status TEXT NOT NULL, doc_type TEXT, confidence REAL, team TEXT NOT NULL,"
                " action TEXT NOT NULL, priority TEXT NOT NULL, needs_review INTEGER NOT NULL,"
                " pii_masked INTEGER NOT NULL, latency_ms REAL NOT NULL, attempts INTEGER NOT NULL,"
                " error TEXT, result_json TEXT NOT NULL)")
    old.commit()
    old.close()
    store = RunStore(path)
    process_document("receipt", "t", fake_gemini(), store, today=date(2026, 11, 10))
    assert store.stats()["avg_tokens"] == 1280
