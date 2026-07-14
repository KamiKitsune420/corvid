"""Reader for the Outlook Express ``.dbx`` mail-store format (OE5/OE6).

A ``.dbx`` message store (``Inbox.dbx``, ``Sent Items.dbx``, ...) is a set of
pointer-linked objects: a header points to the root of a B-tree of *message-info*
objects, each of which points to a chain of 512-byte body segments holding the
raw RFC 822 bytes. This reader follows those pointers and reassembles each
message. It reads only message stores; ``Folders.dbx`` / POP3-UIDL / offline
files are rejected. All integers are little-endian.

Layout constants and the traversal are derived from Arne Schloh's canonical
reverse-engineered spec and cross-checked against the ``undbx`` C source. Reads
are defensively bounds-checked: a malformed store yields whatever messages parse
cleanly rather than raising partway through.
"""

from __future__ import annotations

import logging
from collections.abc import Iterator
from pathlib import Path

from .base import ImportedFolder, ImportedMessage

log = logging.getLogger("corvid.import.dbx")

_MAGIC = 0xFE12ADCF
_TYPE_MESSAGE_STORE = 0x6F74FDC5  # bytes C5 FD 74 6F at offset 0x04

_ITEM_COUNT_OFF = 0xC4
_ROOT_PTR_OFF = 0xE4

# Index tree node (0x27C bytes total).
_TREE_CHILD0_OFF = 0x08
_TREE_ENTRY_COUNT_OFF = 0x11
_TREE_SUBTREE_TOTAL_OFF = 0x14
_TREE_ENTRIES_OFF = 0x18
_TREE_ENTRY_SIZE = 12
_TREE_MAX_ENTRIES = 0x33  # 51

# Message-info object.
_INFO_HEADER_OFF = 0x08
_INFO_ATTRS_OFF = 0x0C
_ATTR_ID_BODY_PTR = 0x04

# Body segment (0x10-byte header + up to 0x200 data).
_SEG_USED_OFF = 0x08
_SEG_NEXT_OFF = 0x0C
_SEG_DATA_OFF = 0x10
_SEG_MAX_DATA = 0x200


def _u32(buf: bytes, off: int) -> int:
    if off < 0 or off + 4 > len(buf):
        return 0
    return int.from_bytes(buf[off : off + 4], "little")


def _u16(buf: bytes, off: int) -> int:
    if off < 0 or off + 2 > len(buf):
        return 0
    return int.from_bytes(buf[off : off + 2], "little")


def is_message_store(buf: bytes) -> bool:
    """True if ``buf`` is an OE message store (as opposed to Folders.dbx etc.)."""
    return len(buf) >= 0xE8 and _u32(buf, 0) == _MAGIC and _u32(buf, 0x04) == _TYPE_MESSAGE_STORE


def _iter_info_offsets(buf: bytes) -> Iterator[int]:
    """Walk the index B-tree, yielding every message-info object offset."""
    root = _u32(buf, _ROOT_PTR_OFF)
    if not root:
        return
    visited: set[int] = set()
    stack = [root]
    while stack:
        node = stack.pop()
        if node in visited or node <= 0 or node + _TREE_ENTRIES_OFF > len(buf):
            continue
        visited.add(node)
        count = min(buf[node + _TREE_ENTRY_COUNT_OFF], _TREE_MAX_ENTRIES)
        child0 = _u32(buf, node + _TREE_CHILD0_OFF)
        if child0:
            stack.append(child0)
        for i in range(count):
            entry = node + _TREE_ENTRIES_OFF + i * _TREE_ENTRY_SIZE
            if entry + _TREE_ENTRY_SIZE > len(buf):
                break
            value_ptr = _u32(buf, entry)
            child_next = _u32(buf, entry + 4)
            if value_ptr:
                yield value_ptr
            if child_next:
                stack.append(child_next)


def _body_pointer(buf: bytes, info: int) -> int:
    """Resolve a message-info object's pointer to its first body segment (0 if none)."""
    if info + _INFO_ATTRS_OFF > len(buf):
        return 0
    header = _u32(buf, info + _INFO_HEADER_OFF)
    count = (header >> 16) & 0xFF
    attr_base = info + _INFO_ATTRS_OFF
    data_base = attr_base + 4 * count
    for i in range(count):
        attr = attr_base + 4 * i
        if attr + 4 > len(buf):
            break
        value = _u32(buf, attr)
        typ = value & 0xFF
        payload = (value >> 8) & 0xFFFFFF
        if (typ & 0x7F) != _ATTR_ID_BODY_PTR:
            continue
        if typ & 0x80:  # direct: the 3-byte payload *is* the body offset
            return payload
        return _u32(buf, data_base + payload)  # indirect: payload indexes the data area
    return 0


def _read_body(buf: bytes, first_segment: int) -> bytes:
    """Reassemble the raw RFC 822 bytes by following the segment chain."""
    out = bytearray()
    seg = first_segment
    visited: set[int] = set()
    while seg and seg not in visited:
        visited.add(seg)
        if seg + _SEG_DATA_OFF > len(buf):
            break
        used = _u16(buf, seg + _SEG_USED_OFF)
        nxt = _u32(buf, seg + _SEG_NEXT_OFF)
        if used == 0 or used > _SEG_MAX_DATA:
            break
        start = seg + _SEG_DATA_OFF
        out += buf[start : start + used]
        seg = nxt
    return bytes(out)


class DbxImporter:
    """Reads an Outlook Express ``.dbx`` message store as one folder.

    Read/unread and other OE-specific flags are not recovered; imported messages
    default to read (these are archival mail). Messages whose body was never
    downloaded (headers-only in OE) are skipped.
    """

    def __init__(self, path: Path, *, folder_name: str | None = None) -> None:
        self._path = path
        self._folder_name = folder_name or path.stem or path.name

    def folders(self) -> Iterator[ImportedFolder]:
        buf = self._path.read_bytes()
        if len(buf) < 0xE8 or _u32(buf, 0) != _MAGIC:
            raise ValueError(f"{self._path.name} is not an Outlook Express .dbx file.")
        if not is_message_store(buf):
            raise ValueError(
                f"{self._path.name} is a .dbx file but not a message store "
                "(Folders.dbx, POP3 UIDL, and offline stores hold no messages)."
            )
        yield ImportedFolder(self._folder_name, self._iter_messages(buf))

    def _iter_messages(self, buf: bytes) -> Iterator[ImportedMessage]:
        for info in _iter_info_offsets(buf):
            body_ptr = _body_pointer(buf, info)
            if not body_ptr:
                continue
            raw = _read_body(buf, body_ptr)
            if raw:
                yield ImportedMessage(raw=raw, seen=True)
