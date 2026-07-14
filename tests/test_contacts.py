from __future__ import annotations

import sqlite3

from corvid.domain.entities import Contact, EmailAddress, Message
from corvid.infra.repositories import ContactRepository
from corvid.service.contacts import ContactService


def _contact(name: str, *emails: str) -> Contact:
    return Contact(
        id=None, display_name=name,
        emails=[EmailAddress(address=e, name=name) for e in emails],
    )


def test_contact_crud_with_emails(db: sqlite3.Connection) -> None:
    repo = ContactRepository(db)
    saved = repo.add(_contact("Alice Example", "alice@x.com", "alice@work.com"))
    assert saved.id is not None

    loaded = repo.get(saved.id)
    assert loaded is not None
    assert [e.address for e in loaded.emails] == ["alice@x.com", "alice@work.com"]

    loaded.emails = [EmailAddress("alice@new.com", "Alice")]
    repo.update(loaded)
    assert [e.address for e in repo.get(saved.id).emails] == ["alice@new.com"]  # type: ignore[union-attr]

    repo.delete(saved.id)
    assert repo.get(saved.id) is None


def test_find_by_email_and_search(db: sqlite3.Connection) -> None:
    repo = ContactRepository(db)
    repo.add(_contact("Bob Jones", "bob@acme.com"))
    repo.add(_contact("Carol Smith", "carol@acme.com"))

    assert repo.find_by_email("BOB@ACME.COM") is not None  # case-insensitive
    pairs = repo.search("bob")
    assert ("Bob Jones", "bob@acme.com") in pairs


def test_autocomplete_formats(db: sqlite3.Connection) -> None:
    service = ContactService(ContactRepository(db))
    service.add(_contact("Dave Lee", "dave@x.com"))
    suggestions = service.autocomplete("dav")
    assert suggestions == ["Dave Lee <dave@x.com>"]
    assert service.autocomplete("d") == []  # below minimum prefix length


def test_collect_sender(db: sqlite3.Connection) -> None:
    service = ContactService(ContactRepository(db))
    msg = Message(id=1, folder_id=1, account_id=1, uid=1, message_id="<x>",
                  from_name="Eve", from_addr="eve@x.com")
    created = service.collect_sender(msg)
    assert created is not None and created.display_name == "Eve"
    # Second time the address is already known -> no duplicate.
    assert service.collect_sender(msg) is None
    assert len(service.list()) == 1
