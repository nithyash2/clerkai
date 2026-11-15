from datetime import date

from clerkai.router import decide
from clerkai.schemas import DocType, Extraction, Priority

TODAY = date(2026, 11, 10)


def make(**kw):
    base = dict(doc_type=DocType.INVOICE, summary="test", confidence=0.95)
    base.update(kw)
    return Extraction(**base)


def test_overdue_invoice_is_urgent():
    d = decide(make(due_date=date(2026, 10, 31), amount=1320), TODAY)
    assert d.priority is Priority.URGENT
    assert d.team == "Bookkeeping" and not d.needs_review


def test_due_soon_is_high():
    assert decide(make(due_date=date(2026, 11, 14)), TODAY).priority is Priority.HIGH


def test_ato_notice_always_reviewed():
    d = decide(make(doc_type=DocType.ATO_NOTICE), TODAY)
    assert d.needs_review and d.team == "Tax" and d.priority is Priority.HIGH


def test_low_confidence_goes_to_review():
    assert decide(make(confidence=0.5), TODAY).needs_review


def test_high_value_goes_to_review():
    d = decide(make(amount=17_600), TODAY)
    assert d.needs_review and any("high value" in r for r in d.reasons)


def test_client_query_gets_draft_reply():
    d = decide(make(doc_type=DocType.CLIENT_QUERY), TODAY)
    assert d.action == "draft_reply" and d.team == "Client Services"
