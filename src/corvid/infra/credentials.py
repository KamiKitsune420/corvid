"""Credential storage.

Passwords are never written to the config file or database. This module provides
a small ``CredentialStore`` interface with three implementations:

* ``KeyringCredentialStore``  - OS vault via the optional ``keyring`` package.
* ``DpapiCredentialStore``    - Windows DPAPI (no third-party dependency), data
                                encrypted at rest under the current user account.
* ``MemoryCredentialStore``   - process-only, for tests.

``get_default_store`` picks the best available option for the platform.
"""

from __future__ import annotations

import base64
import json
import logging
import sys
from pathlib import Path
from typing import Protocol, cast, runtime_checkable

from ..errors import ConfigError

log = logging.getLogger("corvid.credentials")


def account_service(account_id: int) -> str:
    """Canonical service key for an account's primary password."""
    return f"corvid.account.{account_id}"


@runtime_checkable
class CredentialStore(Protocol):
    def get(self, service: str, username: str) -> str | None: ...
    def set(self, service: str, username: str, secret: str) -> None: ...
    def delete(self, service: str, username: str) -> None: ...


class MemoryCredentialStore:
    """In-memory store; secrets vanish when the process exits."""

    def __init__(self) -> None:
        self._data: dict[tuple[str, str], str] = {}

    def get(self, service: str, username: str) -> str | None:
        return self._data.get((service, username))

    def set(self, service: str, username: str, secret: str) -> None:
        self._data[(service, username)] = secret

    def delete(self, service: str, username: str) -> None:
        self._data.pop((service, username), None)


class KeyringCredentialStore:
    """Backed by the OS credential vault via the ``keyring`` package."""

    def __init__(self) -> None:
        try:
            import keyring  # noqa: PLC0415 - optional dependency, imported lazily
        except ImportError as exc:  # pragma: no cover - depends on environment
            raise ConfigError(
                "The 'keyring' package is not installed.",
                user_message="Secure credential storage is unavailable.",
            ) from exc
        self._keyring = keyring

    def get(self, service: str, username: str) -> str | None:
        return cast("str | None", self._keyring.get_password(service, username))

    def set(self, service: str, username: str, secret: str) -> None:
        self._keyring.set_password(service, username, secret)

    def delete(self, service: str, username: str) -> None:
        try:
            self._keyring.delete_password(service, username)
        except Exception:  # noqa: BLE001 - keyring raises if absent; treat as no-op
            pass


class DpapiCredentialStore:
    """Windows DPAPI-encrypted JSON file store (no third-party dependency).

    Secrets are protected with ``CryptProtectData`` (current-user scope) so the
    on-disk blob is unreadable by other users and unusable off the machine.
    """

    def __init__(self, path: Path) -> None:
        if not sys.platform.startswith("win"):  # pragma: no cover - platform guard
            raise ConfigError("DPAPI credential storage is only available on Windows.")
        self._path = path

    # -- DPAPI via ctypes ---------------------------------------------------
    @staticmethod
    def _crypt(data: bytes, *, protect: bool) -> bytes:
        import ctypes
        from ctypes import wintypes

        class DATA_BLOB(ctypes.Structure):
            _fields_ = [("cbData", wintypes.DWORD), ("pbData", ctypes.POINTER(ctypes.c_char))]

        def to_blob(raw: bytes) -> DATA_BLOB:
            buf = ctypes.create_string_buffer(raw, len(raw))
            return DATA_BLOB(len(raw), ctypes.cast(buf, ctypes.POINTER(ctypes.c_char)))

        windll = getattr(ctypes, "windll")  # win32-only; guarded by platform check  # noqa: B009
        crypt32 = windll.crypt32
        kernel32 = windll.kernel32
        in_blob = to_blob(data)
        out_blob = DATA_BLOB()
        fn = crypt32.CryptProtectData if protect else crypt32.CryptUnprotectData
        # Signature is identical for both calls: (in, desc, entropy, reserved, prompt, flags, out)
        if not fn(ctypes.byref(in_blob), None, None, None, None, 0, ctypes.byref(out_blob)):
            raise ConfigError("Windows DPAPI operation failed.")
        try:
            return ctypes.string_at(out_blob.pbData, out_blob.cbData)
        finally:
            kernel32.LocalFree(out_blob.pbData)

    def _load(self) -> dict[str, str]:
        if not self._path.exists():
            return {}
        try:
            return cast("dict[str, str]", json.loads(self._path.read_text(encoding="utf-8")))
        except (OSError, json.JSONDecodeError):
            return {}

    def _save(self, data: dict[str, str]) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self._path.with_suffix(self._path.suffix + ".tmp")
        tmp.write_text(json.dumps(data, indent=2), encoding="utf-8")
        tmp.replace(self._path)

    @staticmethod
    def _key(service: str, username: str) -> str:
        return f"{service}\x00{username}"

    def get(self, service: str, username: str) -> str | None:
        blob = self._load().get(self._key(service, username))
        if blob is None:
            return None
        plaintext = self._crypt(base64.b64decode(blob), protect=False)
        return plaintext.decode("utf-8")

    def set(self, service: str, username: str, secret: str) -> None:
        data = self._load()
        protected = self._crypt(secret.encode("utf-8"), protect=True)
        data[self._key(service, username)] = base64.b64encode(protected).decode("ascii")
        self._save(data)

    def delete(self, service: str, username: str) -> None:
        data = self._load()
        if data.pop(self._key(service, username), None) is not None:
            self._save(data)


def get_default_store(data_dir: Path) -> CredentialStore:
    """Return the most secure credential store available on this platform."""
    try:
        store = KeyringCredentialStore()
        log.debug("using keyring credential store")
        return store
    except ConfigError:
        pass
    if sys.platform.startswith("win"):
        log.debug("using DPAPI credential store")
        return DpapiCredentialStore(data_dir / "credentials.json")
    log.warning(
        "No OS credential vault available; falling back to in-memory storage. "
        "Install 'keyring' for secure persistence."
    )
    return MemoryCredentialStore()
