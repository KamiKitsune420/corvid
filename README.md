# Corvid

A modern, cross-platform desktop email & news client inspired by the workflow and
UX spirit of Outlook Express — rebuilt to be maintainable and secure on current
systems. The legacy OE/WinXP source in the parent repository is used as
behavioral inspiration only, never for code reuse.

> **Status:** All 7 phases complete, plus the full product scope. Foundation,
> accounts + IMAP/SMTP sync, the 3-pane desktop UI, compose/send (plain + HTML,
> attachments, drafts, reply, record-to-Sent), local search (FTS5) + message
> rules, contacts/address book with autocomplete, settings, and packaging
> (PyInstaller) + crash reporting. Now also: **POP3** receive accounts, **NNTP
> newsgroups** (subscribe, read threads, post/reply — the "news" half of an OE
> client), and a **legacy importer** for Outlook Express `.dbx` stores plus
> mbox / Maildir / `.eml`. The UI is built keyboard-first with screen-reader
> names (see Accessibility). Launch with `corvid gui`.

## Requirements

- Python 3.12+
- wxPython 4.2+ for the desktop UI (`pip install -e ".[ui]"`)
- Optionally `keyring` for OS-vault password storage; on Windows, Corvid falls
  back to a DPAPI-encrypted store with no extra dependency.

## Setup

```bash
cd corvid
python -m venv .venv
# Windows:  .venv\Scripts\activate
# POSIX:    source .venv/bin/activate
pip install -e ".[dev]"          # add ",ui" once Phase 3 lands
```

No third-party packages are required to run or test the Phase 1 core — it is
pure standard library.

## Run

The easiest way (no commands to remember) — **double-click `run.bat`** on
Windows, or:

```bash
python run.py          # launch the desktop app (normal per-user data location)
python run.py --dev    # launch against a throwaway ./_devdata folder, for testing
```

Or use the CLI directly:

```bash
python -m corvid version          # print version
python -m corvid init             # create config + database (idempotent)
python -m corvid info             # show paths, schema version, row counts
python -m corvid gui              # launch the desktop UI
```

In the UI: **File → Add Account** to add an IMAP/SMTP (or **POP3**, or **NNTP
news**) account. For mail you normally type only display name, email, and
password — the **server settings are auto-detected from the email domain**
(Gmail, Outlook, Yahoo, iCloud, and more) and hidden under **Advanced**. For
Gmail/Outlook a **Sign in with Google/Microsoft** button appears when OAuth is
configured (see below); otherwise, if the provider needs an **app password**, a
help link appears. Then **Send / Receive** (F9) to sync.

### OAuth ("Sign in with Google / Microsoft")

> **Note:** the OAuth sign-in button is **disabled in the UI for now** (set
> `_OAUTH_SIGN_IN_ENABLED = True` in `ui/account_dialog.py` to re-enable it). A
> *verified public* Google client requires a paid security assessment, so Corvid
> leads with **app passwords** instead. All the OAuth code below remains in place
> and works — it's just the button that's hidden until verification is arranged.

Corvid supports OAuth 2.0 (authorization-code + PKCE, loopback redirect) with
**XOAUTH2** IMAP/SMTP. It must be registered once with each provider to get a
**client id** (this is free for personal/testing use):

- **Google** — in a [Google Cloud](https://console.cloud.google.com/) project,
  create an OAuth **Desktop app** client; copy its id + secret.
- **Microsoft** — in [Azure/Entra](https://entra.microsoft.com/), register an app
  with a **Mobile and desktop** platform (public client, no secret); copy its id.

Put them in `config.json` (see [`config.example.json`](./config.example.json)):

```json
"oauth": {
  "google_client_id": "…apps.googleusercontent.com",
  "google_client_secret": "…",
  "microsoft_client_id": "…"
}
```

Then Add Account shows **Sign in** — it opens your browser, you approve, and only
a refresh token is stored (in the OS credential vault; the access token is
refreshed on demand). Without a client id, the app-password flow is used instead.
**iCloud** offers no mail OAuth — use an app-specific password there. IMAP syncs folders and headers, POP3 downloads
new mail into a local Inbox (with an optional *leave-on-server* copy), and a news
account downloads article headers for your subscribed groups. Selecting a message
downloads and displays its body (HTML rendered safely — scripts stripped, remote
images blocked by default — or plain text), with attachments you can **Save** or
**Open**. Opening a message **marks it read on the server**, and the **Message**
menu (Mark Read/Unread, Toggle Flag, Delete) writes those changes back over IMAP
(delete moves to Trash when available). **New Message** (Ctrl+N) /
**Reply** (Ctrl+R) open the composer (plain or HTML, attachments, recipient
**autocomplete** from contacts, **Address Book** picker, save draft); sent mail
is recorded to the server's Sent folder. The toolbar **search box** runs a
full-text query across messages. The **Tools** menu has the **Address Book**
(Ctrl+Shift+B), **Message Rules** (match From/To/Subject → mark read / flag /
delete / move), **Newsgroups...** (browse/subscribe on a news account), and
**Settings** (Ctrl+,: theme, sync, security, per-account signatures). Passwords
go to the OS credential vault, never the config/database.

**Newsgroups.** On a news account, **Tools → Newsgroups...** lists the server's
groups (filter or add by name) to subscribe; each subscribed group appears in the
folder tree, **Send / Receive** downloads article headers, selecting an article
fetches it, and **New Message** / **Reply** post an article or threaded follow-up.

**Importing mail.** **File → Import Messages...** brings a legacy or local store
into an account: an Outlook Express `.dbx` file, a Unix `mbox`, a Maildir tree, or
a single `.eml` / folder of `.eml` files. Imported mail is stored locally (never
uploaded) and reads and searches like any other message. From the CLI:
`corvid import <path>` (auto-detects the format; `--kind` forces it).

**Importing contacts.** The **Address Book → Import...** button (and
`corvid import-contacts <path>`) reads vCard (`.vcf`), CSV, Windows Contacts
`.contact` XML, and LDIF, deduped by email. A Windows Address Book `.wab` file is
recognized but — since its binary format is undocumented — Corvid points you to
export it to vCard/CSV from Windows first (how `.wab` migration is done anyway).

## Accessibility

The desktop UI follows WCAG keyboard/focus guidance and wxPython's accessibility
model:

- **Fully keyboard-operable** — every control is in the Tab order with logical
  focus order and no keyboard traps; primary actions have mnemonics (`&`) and
  accelerators (F9, Ctrl+N/R, Ctrl+,, Ctrl+Shift+B).
- **Screen-reader names** — text fields that rely on an adjacent label get an
  explicit accessible name via `SetName`, so NVDA/VoiceOver announce them
  meaningfully instead of a generic control name.
- **Never color-alone** — unread mail is shown in **bold**, not just color.
- **Native theming** — colors/fonts come from the OS, so high-contrast and
  font-scaling settings are respected.
- **Conversation grouping** — the message list is a native tree; replies nest
  under a collapsible conversation node that NVDA announces with its level and
  expanded/collapsed state. **Left/Right collapse/expand** a conversation; Enter
  on it toggles too. Grouping uses the real `In-Reply-To`/`References` headers and
  can be turned off under **View → Group by Conversation** (older mail groups once
  re-synced, since Corvid now stores those headers).

## Packaging (Windows)

```bash
pip install -e ".[ui]" pyinstaller
pyinstaller corvid.spec          # -> dist/Corvid/Corvid.exe
```

Uncaught exceptions are written to a timestamped `crash-*.log` in the log
directory (alongside the rotating JSONL logs) for easy diagnosis.

Use `--root DIR` to run against a self-contained, portable data directory
(handy for development and demos) instead of the per-user OS location:

```bash
python -m corvid --root ./_devdata init
```

By default, files live in per-user locations:

| Platform | Config | Data / logs / attachments |
| --- | --- | --- |
| Windows | `%APPDATA%\ALS-Software\Corvid` | `%LOCALAPPDATA%\ALS-Software\Corvid` |
| macOS | `~/Library/Application Support/Corvid` | same |
| Linux | `$XDG_CONFIG_HOME/corvid` | `$XDG_DATA_HOME/corvid` |

On Windows the data nests under the `ALS-Software` publisher folder, matching the
installer's `Program Files\ALS-Software\corvid` layout.

## Updating Corvid

Corvid checks for new versions through **GitHub Releases**. Open **Help → Check
for Updates** (or see the current version under **Help → About Corvid**). The
dialog compares your running version against the latest published release of
[`KamiKitsune420/corvid`](https://github.com/KamiKitsune420/corvid):

- **Up to date** — it says so and does nothing further.
- **A newer version exists** — it shows the version and its release notes, and a
  **Download Update** button fetches the installer (`CorvidSetup-<version>.exe`)
  to your `Downloads` folder with a progress bar, then reveals it in Explorer.
- **Couldn't check** (offline, etc.) — it reports that; nothing is changed.

To finish updating, close Corvid and run the downloaded installer. It reinstalls
in place over `Program Files\ALS-Software\corvid`; your accounts, mail, and
settings (in `%APPDATA%`/`%LOCALAPPDATA%`) are untouched. The check and download
run on background threads, so the UI stays responsive, and the status area is a
screen-reader-readable text field that announces each step. Nothing is
downloaded or installed without your explicit action.

## Test

```bash
pytest                # 188 tests, pure stdlib
mypy src              # strict type checking (the wx UI layer is excluded — see pyproject)
ruff check src tests  # lint
```

## Project layout

```
corvid/
├── src/corvid/
│   ├── app/        bootstrap, config, paths, logging, job queue
│   ├── domain/     entities & value objects (storage-agnostic), conversation
│   │               threading (threads.py)
│   ├── infra/      db (connection + migrations), repositories, credentials,
│   │               mail/ (IMAP store, SMTP sender, NNTP client/store, POP3
│   │               receiver behind ports), importers/ (dbx/mbox/maildir/eml),
│   │               contact_importers/ (vcard/csv/.contact/ldif/wab)
│   ├── service/    use-cases: accounts, sync, send, search, rules, contacts,
│   │               news, pop3, import, contact_import, delivery (shared store),
│   │               updates (GitHub Releases check/download)
│   ├── ui/         wxPython 3-pane shell, dialogs, wx-free presenters,
│   │               accessibility helpers
│   ├── cli.py      operational command-line entry point
│   └── errors.py   error taxonomy
├── packaging/      PyInstaller GUI entry point
├── corvid.spec     PyInstaller build spec
├── tests/
├── docs/oe_mapping.md
├── ARCHITECTURE.md
└── pyproject.toml
```

See [`ARCHITECTURE.md`](./ARCHITECTURE.md) for the layering rules and
[`docs/oe_mapping.md`](./docs/oe_mapping.md) for how legacy OE concepts map to
modern equivalents.

## Roadmap

1. **Foundation** ✅ — scaffolding, config, logging, SQLite schema, job queue
2. **Accounts + Sync** ✅ — IMAP/SMTP adapters, credentials, folder/header sync
3. **Core UI** ✅ — 3-pane shell, folder tree, list, preview, Send/Receive
4. **Compose + Send** ✅ — composer (plain/HTML), attachments, SMTP send, drafts
5. **Search + Rules** ✅ — FTS5 search, rule engine + actions
6. **Contacts + polish** ✅ — address book, autocomplete, settings, signatures
7. **Packaging + QA** ✅ — PyInstaller spec, crash logs, expanded tests

### Beyond the phased plan (full product scope)

8. **POP3** ✅ — POP3 receive accounts (UIDL de-dup, leave-on-server option)
9. **News (NNTP)** ✅ — newsgroup subscribe/sync/read + post/follow-up, over a
   stdlib-socket NNTP client (no deprecated `nntplib`)
10. **Legacy mail import** ✅ — Outlook Express `.dbx` reader + mbox / Maildir / `.eml`
11. **Contact import** ✅ — vCard / CSV / Windows Contacts `.contact` / LDIF
    (Windows Address Book `.wab` is recognized and routed to the export path)
12. **OAuth 2.0** ✅ — "Sign in with Google/Microsoft" (XOAUTH2) via a config-set
    client id; refresh token in the vault, access token refreshed on demand
13. **Runs in the background** ✅ — periodic auto-fetch, a Windows new-mail toast,
    and optional close-to-the-system-tray (all toggleable in Settings)
14. **Calendar** ✅ — a local calendar (month picker + day agenda + event editor);
    **Ctrl+Tab** switches between Mail and Calendar
