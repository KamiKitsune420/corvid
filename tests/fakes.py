"""Test doubles for the mail-store port."""

from __future__ import annotations

from corvid.infra.mail.types import FolderInfo, FolderStatus, HeaderEnvelope


class FakeMailStore:
    """An in-memory MailStore for exercising the sync service."""

    def __init__(
        self,
        folders: list[FolderInfo],
        mailboxes: dict[str, tuple[FolderStatus, list[HeaderEnvelope]]],
    ) -> None:
        self._folders = folders
        self._mailboxes = mailboxes
        self._selected: str | None = None
        self.connected = False
        self.raw_by_uid: dict[int, bytes] = {}
        self.flag_ops: list[tuple[int, tuple[str, ...], bool]] = []
        self.moves: list[tuple[int, str]] = []
        self.deletes: list[int] = []

    def connect(self) -> None:
        self.connected = True

    def close(self) -> None:
        self.connected = False

    def __enter__(self) -> FakeMailStore:
        self.connect()
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    def list_folders(self) -> list[FolderInfo]:
        return list(self._folders)

    def select(self, remote_name: str, *, readonly: bool = True) -> FolderStatus:
        self._selected = remote_name
        return self._mailboxes[remote_name][0]

    def search_uids(self, min_uid: int | None = None) -> list[int]:
        assert self._selected is not None
        uids = sorted(e.uid for e in self._mailboxes[self._selected][1])
        if min_uid is not None:
            uids = [u for u in uids if u > min_uid]
        return uids

    def fetch_headers(self, uids: list[int]) -> list[HeaderEnvelope]:
        assert self._selected is not None
        wanted = set(uids)
        return [e for e in self._mailboxes[self._selected][1] if e.uid in wanted]

    def fetch_raw(self, uid: int) -> bytes:
        return self.raw_by_uid.get(uid, b"")

    def store_flags(self, uid: int, flags: tuple[str, ...], *, add: bool) -> None:
        self.flag_ops.append((uid, tuple(flags), add))

    def move(self, uid: int, dest_remote_name: str) -> None:
        self.moves.append((uid, dest_remote_name))

    def delete(self, uid: int) -> None:
        self.deletes.append(uid)

    # -- test helpers -------------------------------------------------------
    def set_mailbox(
        self, remote_name: str, status: FolderStatus, envelopes: list[HeaderEnvelope]
    ) -> None:
        self._mailboxes[remote_name] = (status, envelopes)
