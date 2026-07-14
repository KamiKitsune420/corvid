from __future__ import annotations

from corvid.ui.accessibility import clean_label


def test_clean_label_strips_mnemonic_and_colon() -> None:
    assert clean_label("&IMAP host:") == "IMAP host"
    assert clean_label("Subjec&t:") == "Subject"
    assert clean_label("To:") == "To"
    assert clean_label("Address &Book...") == "Address Book..."
