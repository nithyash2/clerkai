from clerkai.masking import is_valid_luhn, is_valid_tfn, mask_pii


def test_valid_tfn_is_masked():
    r = mask_pii("Tax file number: 123 456 782")
    assert "[TFN]" in r.text
    assert "123 456 782" not in r.text
    assert r.counts == {"tfn": 1}


def test_nine_digit_number_failing_checksum_is_kept():
    # Not a real TFN, so it should not be hidden (e.g. a reference number).
    assert not is_valid_tfn("123456789")
    assert "123 456 789" in mask_pii("Ref 123 456 789").text


def test_card_number_masked_with_luhn():
    assert is_valid_luhn("4111111111111111")
    r = mask_pii("Paid by card 4111 1111 1111 1111 today")
    assert "[CARD]" in r.text and "4111" not in r.text


def test_bank_details_masked():
    r = mask_pii("BSB 063-019 Account 10458826")
    assert "063-019" not in r.text and "10458826" not in r.text
    assert r.counts == {"bsb": 1, "account": 1}


def test_money_and_dates_untouched():
    text = "Total due $1,320.00 by 31/10/2026, invoice INV-20461"
    assert mask_pii(text).text == text


def test_abn_is_not_mistaken_for_a_tfn():
    # The last 9 digits of this ABN pass the TFN checksum, but ABNs are public.
    text = "ABN 33 102 417 032"
    assert mask_pii(text).text == text
