# Outlook Express → Corvid: behavior mapping

How legacy Outlook Express concepts (observed in the parent source tree, whose
internal codename was **Athena** — see `athena.inc`, `athenant.bat`) map to
Corvid's modern implementation. Every row below is now implemented; the table
spans storage/identity foundations through the mail, news, POP3, and import
features that complete the original product scope.

| # | Legacy OE behavior observed | Corvid decision | Rationale |
|---|------------------------------|-----------------|-----------|
| 1 | **Message stores** kept as per-folder `.dbx` files in the user's *Store Folder*, with a `Folders.dbx` index. Custom binary format, prone to corruption and a 2 GB limit. | Single **SQLite** database (WAL) with `folders` + `messages` tables; raw RFC 822 bodies stored as files under `attachments/`-style blob storage, referenced by `messages.raw_path`. | One transactional, queryable, crash-resilient store. Indexed queries replace linear `.dbx` scans; no 2 GB ceiling. |
| 2 | **Identities** isolate separate stores/settings per person on one OS account; switching identities re-points the whole app. | `identities` table scoped to an `account` (`is_default` flag), plus per-user `AppPaths`. Multi-account is first-class rather than an identity-switch modal. | Modern users expect several accounts visible at once; identities become per-account sending personas instead of a global mode switch. |
| 3 | **Account Wizard** collects server/auth step-by-step; servers and ports typed by hand. | Add-Account asks only for display name, email, and password; server settings are **auto-detected from the email domain** (`infra/autodiscovery`) and tucked under "Advanced". Username defaults to the email. Providers that require an **app password** (Gmail/Outlook/Yahoo/...) show a help link. | Beginners never type a hostname or port; the manual fields remain for uncommon servers, and the app-password hint prevents the #1 "why won't it connect" failure now that big providers disabled basic-auth passwords. |
| 4 | **Read/unread & flags** tracked as per-message state bits in the `.dbx` record (seen, replied, flagged, marked for download). | Explicit boolean columns `flag_seen/answered/flagged/draft/deleted` on `messages`, mapped to the `MessageFlags` domain value object and to IMAP system flags. | Direct, indexable mapping to IMAP keywords; folder unread counts become a cheap indexed `COUNT`. |
| 5 | **Special folders** (Inbox, Outbox, Sent Items, Deleted Items, Drafts, Junk). | `folders.type` enum (`inbox/sent/drafts/trash/junk/archive/outbox/custom`). | Decouples role from localized display name; lets sync map server special-use folders (RFC 6154) onto known roles. |
| 6 | **Send/Receive** with a modal progress dialog; errors shown mid-flow, blocking the UI. | Background `JobQueue` with cancellation + progress callbacks; non-blocking status surfaced in the status bar. | Keeps the UI responsive on large mailboxes; cancellable, observable operations instead of a frozen modal. |
| 7 | **Message Rules** (mail/news) with conditions → actions, applied on arrival or on demand. | `rules` table storing `match_json` + `actions_json`, run by a filter engine in Phase 5. | Serialized, versionable rule definitions; engine reused for on-arrival and manual "apply now". |
| 8 | **Windows Address Book (WAB)** `.wab` contact store with autocomplete in the composer. | `contacts` + `contact_emails` tables with an indexed `email` column for autocomplete. | Normalized contacts with multiple addresses; index-backed autocomplete. |
| 9 | **HTML mail** rendered in the Internet Explorer (Trident) control, historically with active content enabled. | `wx.html2` rendering behind a **sanitization** layer with **remote content blocked by default** (`SecurityConfig`). | Removes the classic OE malware vector; remote content load becomes an explicit, per-message user choice. |
| 10 | **Plaintext credentials**/weakly protected passwords in the store/registry. | Passwords never persisted in config or DB; OS credential vault (keyring), with a Windows DPAPI-encrypted fallback. | Eliminates at-rest plaintext secrets. |
| 11 | **POP3** accounts (OE's default for many users): download to a local store, optionally leaving a copy on the server. | `receive_protocol` on the account; `Pop3Receiver` (`poplib`) + `Pop3Service` download by **UIDL** into a local Inbox, recording each UIDL so re-polls fetch only new mail; `pop3_leave_on_server` toggles server `DELE`. | Matches OE's POP workflow while sharing the same local `messages` store, search, and rules as IMAP. |
| 12 | **NNTP newsgroups** in the same 3-pane window: subscribe, download headers, read threads, post and follow up. | A newsgroup is a `NEWSGROUP` folder and an article a message; `NntpMailStore` implements the same `MailStore` port (article number = UID) so sync/read reuse the mail path. `NewsService` handles subscribe/post. | Reuses the entire mail pipeline for news; the "email **and news** client" identity is preserved without a parallel stack. |
| 13 | **`.dbx` message stores** and other legacy/interchange mailboxes users want to bring forward. | **File → Import**: a from-scratch `.dbx` reader (header → index B-tree → chained 512-byte body segments) plus mbox / Maildir / `.eml`. Imported messages are stored locally (`uid = NULL`, body cached) so they read/search like synced mail and IMAP sync ignores them. | Lets OE users migrate their actual archives; interchange formats cover Thunderbird/Apple Mail/Dovecot exports. |
| 14 | **Windows Address Book (`.wab`)** contacts and their successors. | **Address Book → Import**: vCard (`.vcf`), CSV, Windows Contacts `.contact` XML, and LDIF, deduped by email. A `.wab` file is recognized but redirected to the standard export path (see rationale). | The `.wab` binary is undocumented and signature-less — the only reverse-engineered description relies on unexplained fields with no documented property layout — so a guessed parser would silently corrupt data. WAB/Windows Contacts export losslessly to vCard/CSV, which is how migration is actually done. |

## Notes

- The `folders`/`messages` schema is deliberately protocol-neutral: IMAP, POP3,
  and NNTP all map onto the same tables, and imported mail joins them unchanged.
- The `.dbx` reader targets the OE5/OE6 message-store format (per Arne Schloh's
  reverse-engineered spec, cross-checked against `undbx`); `Folders.dbx`,
  POP3-UIDL, and offline stores are recognized and rejected as non-message files.
- Contact import is deduped against existing contacts by email, so re-importing a
  file (or importing overlapping exports) never creates duplicates.
