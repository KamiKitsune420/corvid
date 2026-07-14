# Architecture

Corvid uses a clean, layered architecture. Dependencies point **inward**: outer
layers depend on inner ones, never the reverse.

```
            ┌───────────────────────────────────────────┐
            │                  ui/                        │  wxPython views,
            │        (Phase 3 — presenters/views)         │  dialogs, presenters
            └───────────────────┬─────────────────────────┘
                                │ depends on
            ┌───────────────────▼─────────────────────────┐
            │                 domain/                      │  entities, value
            │     entities · use-cases · rules (pure)      │  objects, rules
            └───────────────────┬─────────────────────────┘
                                │ implemented by
            ┌───────────────────▼─────────────────────────┐
            │                 infra/                       │  sqlite repos,
            │   db (connection + migrations) · repos ·     │  imap/smtp adapters,
            │   imap/smtp adapters (later) · file store    │  file storage
            └───────────────────┬─────────────────────────┘
                                │ wired by
            ┌───────────────────▼─────────────────────────┐
            │                  app/                        │  bootstrap, DI,
            │  bootstrap · config · paths · logging · jobs │  config, job queue
            └─────────────────────────────────────────────┘
```

## Layer responsibilities

- **`domain/`** — Storage- and framework-agnostic entities and (later) use-cases
  and rules. Pure Python dataclasses with no imports from `infra`/`ui`/`app`.
  `id is None` marks an unpersisted entity.
- **`infra/`** — Adapters to the outside world: the SQLite database (connection
  factory + forward-only migrations), repositories that map entities to rows,
  and (later phases) IMAP/SMTP protocol adapters and the on-disk blob store.
- **`app/`** — Composition root. `bootstrap()` resolves paths, loads config,
  configures logging, opens the DB, runs migrations, and starts the job queue,
  returning one `AppContext`. Also owns the background `JobQueue`.
- **`service/`** — Application use-cases that orchestrate repositories and the
  mail adapters: `AccountService` (accounts, credentials, open store/sender),
  `SyncService` (folder list + incremental header sync, optional rule
  application), `SendService` (build + send + record-to-Sent), `SearchService`
  (FTS5 query), and `RuleService` (evaluate + execute rule actions). Services
  depend on the `MailStore`/`Sender` **ports**, never on imaplib/smtplib
  directly. `factory.py` assembles services from a connection so each thread
  builds its own.
- **`ui/`** — wxPython presentation. The widgets (`main_frame`, composer, and
  the account/contacts/rules/settings dialogs) are thin; all data shaping lives
  in `presenters.py`, which is wx-free and unit-tested. The UI depends on
  `AppContext` and services, never on SQLite or sockets directly. `accessibility.py`
  centralizes screen-reader naming and labeled-row helpers.

## Mail adapters and the port boundary

`infra/mail/base.py` defines the `MailStore` protocol (connect, list_folders,
select, search_uids, fetch_headers). `ImapMailStore` implements it over
`imaplib`; tests inject a `FakeMailStore`. Envelope/LIST parsing is factored into
pure functions (`parse_list_line`, `parse_envelope`, `parse_fetch_response`) so
the fiddly IMAP wire format is tested without a live server. `SmtpSender` handles
outbound mail. All adapters translate transport failures into the `errors`
taxonomy (`AuthError`/`TLSError`/`ProtocolError`/`NetworkError`).

**NNTP (news).** `NntpMailStore` *also* implements the `MailStore` port, so
newsgroups reuse `SyncService`/`MessageBodyService` unchanged: a newsgroup is a
folder, an article is a message, the article number plays the role of a UID,
GROUP supplies the folder status, XOVER the header envelopes, and ARTICLE the raw
body. It is built on `NntpClient`, a small RFC 3977 client written directly on
`socket`/`ssl` (not the deprecated, 3.13-removed `nntplib`). `NewsService` adds
the news-only pieces: subscribe/unsubscribe (create/delete `NEWSGROUP` folders)
and posting (`domain/news.build_article` → `NntpClient.post`, with dot-stuffing).

**POP3.** POP3 has a single maildrop and no server folders or flags, so
`Pop3Receiver` (stdlib `poplib`) does *not* implement `MailStore`. `Pop3Service`
downloads new mail (identified by UIDL, recorded in a `pop3_uidls` ledger so
re-polls only fetch new messages; optional leave-on-server) into a local Inbox
via the shared `service/delivery.deliver_raw` helper.

**Importers.** `infra/importers/` reads local stores — `DbxImporter` (a careful
reader of the Outlook Express `.dbx` binary B-tree/segment format), plus
mbox/Maildir/`.eml` via `interchange.py`. `ImportService` maps each source folder
to a local folder and each message through `deliver_raw`. Because imported and
POP3 messages are stored with `uid = NULL` and `body_fetched = True` (raw cached
on disk), they read and search like synced mail and incremental IMAP sync ignores
them; `deliver_raw` is the one shared path that guarantees this.

**Contact importers.** `infra/contact_importers/` yields domain `Contact`s from
vCard, CSV, Windows Contacts `.contact` XML, and LDIF; `ContactImportService`
deduplicates by email before persisting. A `.wab` file is recognized but raises a
guided `ValidationError` (its binary format is undocumented and only heuristically
reverse-engineered, so a parser would silently corrupt data — the standard path is
to export from Windows to vCard/CSV, which Corvid reads).

## Threading model

SQLite connections are thread-affine. The UI thread owns one connection (reads);
each background **sync job opens its own connection** to the same WAL database,
runs to completion, and closes it. Results marshal back to the UI via
`wx.CallAfter`. Credentials are read on the worker thread from the OS vault.

## Credentials

`infra/credentials.py` exposes a `CredentialStore` protocol with three backends:
`KeyringCredentialStore` (OS vault, if `keyring` is installed),
`DpapiCredentialStore` (Windows DPAPI via ctypes — encrypted at rest, no third
-party dependency), and `MemoryCredentialStore` (tests). `get_default_store`
selects the best available. Passwords never touch the config file or database.

## Cross-cutting concerns

### Configuration (`app/config.py`)
A tree of typed dataclasses persisted as JSON, written atomically (temp file +
`replace`). Secrets are **never** stored here — account passwords go to the OS
credential vault in a later phase. `validate()` guards invariants on load/save.

### Paths (`app/paths.py`)
`AppPaths` resolves per-OS config/data/log/attachment directories. `paths_for_root()`
produces a single-directory portable layout used by `--root` and tests.

### Logging (`app/logging_setup.py`)
Human-readable console handler plus a rotating JSONL file handler. Structured
context attaches via `logger.info(..., extra={"fields": {...}})`.

### Background jobs (`app/jobs.py`)
A `ThreadPoolExecutor`-backed `JobQueue`. Each job receives a `JobContext` with a
**cooperative** `CancellationToken` and a progress callback. Jobs poll
`ctx.raise_if_cancelled()` at safe points. `JobHandle` exposes status, result,
and cancellation. This keeps sync/send/import work off the UI thread.

### Errors (`errors.py`)
All application errors derive from `CorvidError` and carry a `user_message`
suitable for the UI, while `str(err)` keeps developer detail. Taxonomy:
config · storage (→ migration) · network (→ auth/TLS/protocol) · validation ·
cancellation.

## Database & migrations

- SQLite in **WAL** mode, `foreign_keys = ON`, autocommit connection.
- **Forward-only** migrations (`infra/db/migrations.py`). Each runs in its own
  transaction and is recorded in `schema_migrations`; applied versions are
  skipped on subsequent runs (idempotent). Statements execute individually —
  never via `executescript`, which would implicitly commit and break atomicity.
- v1 establishes the core schema (accounts, identities, folders, messages,
  attachments, contacts, contact_emails, rules, app_meta). v2 adds an FTS5
  search index, degrading gracefully (logged) if the SQLite build lacks FTS5.
  v3 adds the `drafts` table. v4 adds news-account columns (`kind`, `nntp_*`) and
  the `NEWSGROUP` folder role. v5 adds POP3 columns (`receive_protocol`, `pop3_*`)
  and the `pop3_uidls` de-dup ledger. All are additive `ALTER`s that preserve
  existing rows (an existing IMAP account upgrades cleanly to the new schema).

## Compose, search, and rules

- **Compose/send.** `domain/compose.py` holds a `DraftMessage` and a pure
  `build_email_message()` that emits a stdlib `EmailMessage` (plain, or
  multipart/alternative for HTML, plus attachments; Bcc is set as a header and
  stripped by `smtplib` at send time). `SendService` builds, sends via a
  `Sender` port, then best-effort records the message to the server Sent folder
  via IMAP `APPEND` (`MailboxSentRecorder`). Drafts persist in the `drafts`
  table (`DraftRepository`).
- **Reading messages.** Sync stores headers only; the full body is fetched on
  demand the first time a message is opened. `ImapMailStore.fetch_raw` downloads
  the raw RFC 822 bytes (`BODY.PEEK[]`), `MessageBodyService` caches them under
  `messages_dir` as `<id>.eml` (marking `body_fetched`), and `parse_message`
  splits out the text body, HTML body, and attachments. The download runs on the
  job queue (own connection); the result renders via `wx.CallAfter`.
- **HTML safety.** `htmlsanitize.sanitize_html` is an allowlist sanitizer that
  drops scripts/styles/iframes (and their contents), event handlers, `style`
  attributes, and unsafe URL schemes, and removes remote image `src` by default
  (reporting that it did, so the pane can show a "remote content blocked" notice
  honoring `SecurityConfig.block_remote_content`). The preview renders with
  `wx.html.HtmlWindow` — no JavaScript engine, no automatic remote loads — and
  opens links in the system browser. Defense in depth: sanitizer + inert renderer.
- **Attachments.** `PreviewPanel` lists non-inline attachments with Save (to a
  chosen path) and Open (temp file + OS default app).
- **Server write-back.** `MessageActionService` changes server state first
  (`ImapMailStore.store_flags`/`move`/`delete` — UID STORE / UID MOVE with a
  COPY+expunge fallback) and only then updates the local mirror and recomputes
  folder counts, so a network failure leaves both sides consistent. Opening a
  message marks it `\Seen` on the server (piggybacked on the body-fetch job);
  the Message menu performs read/unread, flag, and delete (delete = move to
  Trash when that folder exists). User-initiated only — rule-driven changes
  during sync remain local for now.
- **Search.** `MessageRepository` populates the `messages_fts` index on insert
  (guarded — no-op if FTS5 is absent). `SearchService` runs a sanitized prefix
  `MATCH` query, falling back to `LIKE` when FTS5 is unavailable.
- **Rules.** `domain/rules.py` is a pure engine: conditions (From/To/Subject ×
  contains/equals/startswith/endswith/regex) combined ALL/ANY, ordered by
  priority, producing actions (mark read/unread, flag, delete, move, stop).
  `RuleService` loads rules and executes their actions via repositories;
  `SyncService` applies them to each newly-synced message.
- **Contacts.** `ContactRepository` (contacts + contact_emails) and
  `ContactService` provide CRUD, prefix search (autocomplete), and sender
  collection. The composer's `ContactCompleter` completes the recipient token
  being typed; the Address Book dialog doubles as a recipient picker.

## Conversation threading

Replies are grouped into conversations from their `In-Reply-To` / `References`
headers (stored on `messages` since migration v7; IMAP now fetches them, and the
POP3/import path parses them from raw bytes). The clustering lives in
`domain/threads.py` (`build_threads`): a union-find links any two messages joined
— directly or transitively — by a shared Message-ID, so a whole reply-chain lands
in one `Thread` (ordered oldest-first; threads ordered newest-first). It is pure
and header-only — subject is deliberately *not* used to merge, avoiding false
grouping of unrelated same-subject mail. `MessageListPresenter.conversations`
turns threads into `ConversationGroup` view-models, which `main_frame` renders
into the native message `TreeCtrl` (see the Accessibility note). Grouping is a
persisted toggle (`config.ui.group_by_conversation`); off, each message is its own
single-item group (a flat list). Older mail that predates v7 threads once
re-synced.

## Accessibility

`ui/accessibility.py` is applied across the UI per WCAG 2.1.1 (Keyboard), 2.4.3
(Focus Order), and 4.1.2 (Name/Role/Value): `accessible_name` sets screen-reader
names on otherwise-unlabeled fields, `clean_label` derives them from UI labels
(dropping `&` mnemonics / trailing colons), and `labeled_row` wires a label +
named control in one call. Primary actions carry mnemonics and accelerators;
meaning is never color-only (unread is bold); native theming preserves OS
high-contrast and font scaling.

## Software updates

The updater is a textbook slice through all four layers (`ui → service → domain
← infra`), so it doubles as a worked example of the dependency rule:

- **`domain/updates.py`** — pure rules, no I/O: `parse_version` (tolerant of a
  leading `v` and of junk, which sorts as oldest so a bad tag never looks
  newer), `is_newer`, `select_asset` (prefer the setup `.exe`, fall back to a
  `.zip`), and `evaluate_update`, which combines them into an `UpdateInfo | None`
  decision. Fully unit-tested without a network or wx.
- **`infra/updates.py`** — `GitHubUpdateClient` is the network/JSON boundary:
  `fetch_latest_release()` parses the Releases API into a domain `Release`,
  `download()` streams an asset to disk with a progress callback. Failures are
  wrapped as `NetworkError` with a `user_message`. The HTTP **opener is
  injectable**, so tests drive it with a fake response — no sockets.
- **`service/updates.py`** — `UpdateService` orchestrates: check returns
  `UpdateInfo | None` and *raises* `NetworkError` if the check itself failed, so
  the UI can tell "up to date" (`None`) from "couldn't check" (exception).
  `build_update_service()` wires the client for the `KamiKitsune420/corvid`
  repo, defaulting the running version from `corvid.__version__` and always
  preferring the installer asset (an installed build sits in read-only Program
  Files and can only upgrade by re-running setup).
- **`ui/update_dialog.py`** — a modal that runs the check/download on daemon
  threads and marshals results back with `wx.CallAfter`. Status is a
  **read-only multiline `TextCtrl`** (so NVDA reads each state change in browse
  mode), every control has an `accessible_name`, and Escape closes it. Wired to
  **Help → Check for Updates**; **Help → About Corvid** shows the version.

Nothing installs automatically: the user clicks Download, and the finished
installer is revealed in Explorer for them to run.

## Diagnostics & packaging

`app/crash.py` installs an `excepthook` that writes a timestamped `crash-*.log`
and records it to the structured log. `corvid.spec` builds a one-folder Windows
app from `packaging/corvid_gui.py` (launches straight into the UI).

## Testing

`pytest` with `pythonpath = ["src"]` (no install needed). Phase 1 covers paths,
config round-trip/validation, migration application + idempotency + FK
enforcement, the job queue (success/progress/cancel/failure), and end-to-end
bootstrap.
