import json
from datetime import date

from clerkai.entities import match_entity, tfn_hash
from clerkai.llm import OfflineClient
from clerkai.pipeline import process_document
from clerkai.tools import DATA_DIR


def test_abn_picks_the_exact_entity():
    m = match_entity("Activity statement reminder\nABN: 98 925 810 340")
    assert m.status == "matched" and m.entity == "Okafor Holdings Pty Ltd" and m.method == "abn"


def test_tfn_matches_by_hash():
    m = match_entity("Notice of assessment\nTax file number: 123 456 782")
    assert m.entity == "Daniel Okafor" and m.method == "tfn"


def test_raw_tfns_are_never_stored_in_client_records():
    raw = (DATA_DIR / "clients.json").read_text()
    assert "123456782" not in raw and "123 456 782" not in raw
    assert tfn_hash("123 456 782") in raw


def test_trustee_wording_files_under_the_trust_not_the_person():
    m = match_entity("Daniel Okafor as trustee for the Okafor Family Trust")
    assert m.entity == "Okafor Family Trust" and m.entity_type == "Trust"


def test_person_name_alone_is_ambiguous_for_a_multi_entity_client():
    m = match_entity("Customer: Daniel Okafor\nLaptop $2,099.00")
    assert m.status == "ambiguous" and len(m.candidates) == 4


def test_single_entity_client_is_matched_by_name():
    m = match_entity("Bill to: Greenleaf Catering")
    assert m.status == "matched" and m.entity == "Greenleaf Catering"


def test_conflicting_tfn_and_name_go_to_a_person():
    m = match_entity("Client: Priya Sandhu\nTFN 123 456 782")
    assert m.status == "ambiguous"


def test_unclear_entity_on_a_receipt_needs_review_with_a_task():
    text = "TAX INVOICE / RECEIPT\nCustomer: Daniel Okafor\nTotal $2,099.00"
    d = process_document(text, "t", OfflineClient(), today=date(2026, 11, 10)).decision
    assert d.needs_review and d.filed_under is None
    assert any("Confirm which entity" in t for t in d.tasks)


def test_unclear_entity_on_a_client_email_does_not_force_review():
    text = "From: Daniel Okafor\nHi James, could you send me the list of documents you need?"
    d = process_document(text, "t", OfflineClient(), today=date(2026, 11, 10), draft_replies=False).decision
    assert not any("entity unclear" in r for r in d.reasons)


def test_every_entity_has_a_type_from_the_known_set():
    clients = json.loads((DATA_DIR / "clients.json").read_text())
    types = {e["type"] for c in clients for e in c["entities"]}
    assert types <= {"Individual", "Trust", "Company", "SMSF", "Partnership", "Sole trader"}


def test_agent_tool_never_returns_tfn_hashes_to_the_llm():
    from clerkai.tools import lookup_client

    record = lookup_client("Daniel Okafor")
    assert "tfn_sha256" not in json.dumps(record)
    assert {"name": "Okafor Family Trust", "type": "Trust"} in record["entities"]
