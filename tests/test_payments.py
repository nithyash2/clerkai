from datetime import date

from clerkai.llm import OfflineClient
from clerkai.payments import check_payment_details, find_supplier
from clerkai.pipeline import process_document

HARBOURVIEW = "TAX INVOICE\nHarbourview Office Supplies Pty Ltd\nABN 33 102 417 032\nBill to: Brightside Physio Clinic\nTotal due $1,452.00\n"


def test_matching_details_pass_without_a_hold():
    c = check_payment_details(HARBOURVIEW + "BSB 063-019 Account 10458826", is_invoice=True)
    assert c.status == "match" and c.task is None


def test_silent_change_is_caught_without_any_warning_words():
    c = check_payment_details(HARBOURVIEW + "Pay to BSB 063-019 Account 91834470", is_invoice=True)
    assert c.status == "mismatch" and c.changed == ["account"]
    assert "(03) 9555 0142" in c.task  # the phone number on file, not one from the email


def test_full_numbers_never_appear_in_reasons_or_tasks():
    c = check_payment_details(HARBOURVIEW + "BSB 062-692 Account 91834470", is_invoice=True)
    text = f"{c.reason} {c.task}"
    assert "91834470" not in text and "062692" not in text and "ending 470" in text


def test_supplier_is_found_by_abn_even_with_a_different_name():
    assert find_supplier("Harbour View Supplies\nABN 33102417032")["name"].startswith("Harbourview")


def test_unknown_supplier_invoice_needs_verification():
    c = check_payment_details("TAX INVOICE\nSwift Print\nBSB 112-879 Account 48120336", is_invoice=True)
    assert c.status == "unknown_supplier"


def test_client_refund_details_are_left_to_the_fraud_flag():
    c = check_payment_details("Please update our refund details to BSB 033-088, account number 284716", is_invoice=False)
    assert c.status == "none"


def test_pipeline_holds_payment_and_creates_a_task():
    r = process_document(HARBOURVIEW + "Due date: 28/11/2026\nBSB 062-692 Account 91834470",
                         "t", OfflineClient(), today=date(2026, 11, 10))
    d = r.decision
    assert d.hold and d.needs_review and d.priority.value == "urgent" and d.action == "hold_payment"
    assert d.tasks and "Do not pay" in d.tasks[0]
