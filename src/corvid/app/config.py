"""Application configuration.

Configuration is a tree of typed dataclasses, persisted as JSON. Secrets (account
passwords) are deliberately NOT stored here - those belong in the OS credential
vault (added in a later phase). This file holds only non-sensitive preferences.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from ..errors import ConfigError

CONFIG_SCHEMA_VERSION = 1
_VALID_LEVELS = {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"}


@dataclass(slots=True)
class LoggingConfig:
    level: str = "INFO"
    json_file: bool = True
    max_bytes: int = 5_000_000
    backup_count: int = 5


@dataclass(slots=True)
class SyncConfig:
    interval_seconds: int = 300
    max_concurrent_jobs: int = 4
    header_batch_size: int = 200
    auto_sync: bool = True  # fetch mail periodically (every interval_seconds)


@dataclass(slots=True)
class UiConfig:
    minimize_to_tray: bool = False  # closing/Alt+F4 hides to the system tray
    show_notifications: bool = True  # Windows toast when new mail arrives


@dataclass(slots=True)
class SecurityConfig:
    enforce_tls: bool = True
    block_remote_content: bool = True
    sanitize_html: bool = True


@dataclass(slots=True)
class OAuthConfig:
    """OAuth client credentials for 'Sign in with Google/Microsoft'.

    These identify *Corvid* to the provider (not the user) and come from a free
    Google Cloud / Azure app registration; without them the sign-in buttons are
    disabled. The Google 'secret' for a desktop app is not confidential, so it is
    acceptable to keep here — user tokens still go to the OS credential vault.
    """

    google_client_id: str = ""
    google_client_secret: str = ""
    microsoft_client_id: str = ""

    def is_configured(self, provider: str) -> bool:
        if provider == "google":
            return bool(self.google_client_id)
        if provider == "microsoft":
            return bool(self.microsoft_client_id)
        return False


@dataclass(slots=True)
class AppConfig:
    schema_version: int = CONFIG_SCHEMA_VERSION
    theme: str = "system"
    logging: LoggingConfig = field(default_factory=LoggingConfig)
    sync: SyncConfig = field(default_factory=SyncConfig)
    security: SecurityConfig = field(default_factory=SecurityConfig)
    oauth: OAuthConfig = field(default_factory=OAuthConfig)
    ui: UiConfig = field(default_factory=UiConfig)

    # -- construction -------------------------------------------------------
    @classmethod
    def default(cls) -> AppConfig:
        return cls()

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> AppConfig:
        try:
            return cls(
                schema_version=int(data.get("schema_version", CONFIG_SCHEMA_VERSION)),
                theme=str(data.get("theme", "system")),
                logging=LoggingConfig(**data.get("logging", {})),
                sync=SyncConfig(**data.get("sync", {})),
                security=SecurityConfig(**data.get("security", {})),
                oauth=OAuthConfig(**data.get("oauth", {})),
                ui=UiConfig(**data.get("ui", {})),
            )
        except TypeError as exc:  # unexpected/renamed keys
            raise ConfigError(f"Invalid configuration structure: {exc}") from exc

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    # -- validation ---------------------------------------------------------
    def validate(self) -> AppConfig:
        if self.logging.level not in _VALID_LEVELS:
            raise ConfigError(
                f"Invalid logging level {self.logging.level!r}; "
                f"expected one of {sorted(_VALID_LEVELS)}."
            )
        if self.sync.max_concurrent_jobs < 1:
            raise ConfigError("sync.max_concurrent_jobs must be >= 1.")
        if self.sync.interval_seconds < 0:
            raise ConfigError("sync.interval_seconds must be >= 0.")
        if self.logging.max_bytes < 0 or self.logging.backup_count < 0:
            raise ConfigError("logging rotation values must be >= 0.")
        return self

    # -- persistence --------------------------------------------------------
    @classmethod
    def load(cls, path: Path) -> AppConfig:
        try:
            raw = path.read_text(encoding="utf-8")
        except OSError as exc:
            raise ConfigError(f"Could not read config file {path}: {exc}") from exc
        try:
            data = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise ConfigError(f"Config file {path} is not valid JSON: {exc}") from exc
        return cls.from_dict(data).validate()

    @classmethod
    def load_or_default(cls, path: Path) -> AppConfig:
        return cls.load(path) if path.exists() else cls.default()

    def save(self, path: Path) -> None:
        self.validate()
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(path.suffix + ".tmp")
        tmp.write_text(json.dumps(self.to_dict(), indent=2) + "\n", encoding="utf-8")
        tmp.replace(path)  # atomic on the same filesystem
