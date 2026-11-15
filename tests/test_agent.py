from datetime import date
from pathlib import Path

from clerkai.agent import draft_reply
from clerkai.documents import read_bytes
from clerkai.llm import OfflineClient
from clerkai.pipeline import process_document
from clerkai.router import risk_flags
from clerkai.schemas import DocType, Extraction
from clerkai.tools import lookup_client, search_knowledge

SAMPLES = Path(__file__).parent.parent / "samples"
TODAY = date(2026, 11, 10)


def test_lookup_client_matches_alias_and_rejects_unknown():
    assert lookup_client("Priya Sandhu")["name"] == "Greenleaf Catering"
    assert lookup_client("Totally Unknown Pty Ltd") == {"found": False}


def test_knowledge_search_finds_the_right_procedure():
    top = search_knowledge("client wants to change their bank details")[0]
    assert top["source"] == "bank_detail_changes"


def test_bank_detail_change_is_flagged_as_fraud_risk():
    assert risk_flags("Can you update our refund details to BSB 033-088?")
    assert not risk_flags("Please find our invoice attached.")


def test_client_query_gets_a_grounded_draft_that_needs_review():
    r = process_document((SAMPLES / "05_client_query.txt").read_text(), "q", OfflineClient(), today=TODAY)
    assert r.decision.needs_review  # bank change request
    draft = r.draft
    assert {c["tool"] for c in draft["tool_calls"]} == {"lookup_client", "search_knowledge"}
    assert {"bas_lodgement", "bank_detail_changes"} <= set(draft["sources"])
    assert "Sarah Nguyen" in draft["text"] and "phone" in draft["text"]
    assert draft["approved"] is False


class FakeToolCallingLLM:
    """Stands in for Gemini: chooses tools itself, like function calling does."""

    name = "fake-agent"

    def run_agent(self, system, prompt, tools):
        lookup, search = tools
        client = lookup(name="Greenleaf Catering")
        notes = search(query="BAS lodgement frequency")
        return f"Hi {client['contact']}, {client['accountant']} will confirm ({notes[0]['source']})."


def test_llm_agent_tool_calls_are_recorded():
    ex = Extraction(doc_type=DocType.CLIENT_QUERY, client_name="Greenleaf", summary="q", confidence=0.9)
    d = draft_reply("masked email", ex, FakeToolCallingLLM())
    assert [c.tool for c in d.tool_calls] == ["lookup_client", "search_knowledge"]
    assert d.tool_calls[0].args == {"name": "Greenleaf Catering"}
    assert d.sources[0] == "bas_lodgement"
    assert "Sarah Nguyen" in d.text


def test_eml_files_are_read():
    eml = b"From: Priya <p@x.example>\nSubject: Hi\nContent-Type: text/plain\n\nCan you call me?"
    text = read_bytes(eml, "mail.eml")
    assert "Subject: Hi" in text and "Can you call me?" in text
