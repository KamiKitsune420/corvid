# CLAUDE.md — Corvid

Guidance for AI assistants (and humans) working in this repository. Read this
first. For deeper design detail see `ARCHITECTURE.md`; for user-facing docs see
`README.md`. This file is the working contract; those two are reference.

## Session handoff (2026-07-14) — read this after the Windows restart

All work below is **committed and pushed** to `github.com/KamiKitsune420/corvid`
(public); a restart loses nothing. Current version **0.2.0**, DB migration **v7**.
Last commit `5ab70d9`.

Done this session:
- Public GitHub repo created; installer now per-machine into
  `Program Files\ALS-Software\corvid` (fixed the "ALS-Softwhere" typo). Per-user
  data moved under `%APPDATA%\ALS-Software\Corvid` / `%LOCALAPPDATA%\...`.
- Sibling **SBP** app (`C:\Users\adels\Documents\sbp`) got the same spelling fix
  + one-time data migration; released as its own v1.6 (separate repo).
- Added the GitHub-Releases **updater** (Help → Check for Updates / About).
- Added **conversation grouping**: message list is now a native `wx.TreeCtrl`
  with collapsible reply-threads (Left/Right expand/collapse). Header-based
  (In-Reply-To/References), toggle in View → Group by Conversation.
- Built + published the **v0.2.0 release** with `CorvidSetup-0.2.0.exe`; verified
  the updater discovers it. Installer now **auto-downloads WebView2** if missing.

Pending / next time:
- **User (blind, NVDA) still needs to confirm** the conversation-grouping reads
  well under NVDA, and test the WebView2 auto-download installer on a machine
  without WebView2. Don't claim either works until confirmed.
- Optional: one-time backfill so *existing* already-synced mail threads without a
  full re-sync (parse reply headers from cached `.eml`).
- Security: SBP's git remote has a plaintext PAT in `.git/config` — user
  deferred rotating it.

## What Corvid is

A modern, Outlook Express–inspired **desktop email & news client**. Python 3.12 +
wxPython 4.2.5, Windows-first (also runs on macOS/Linux). Supports IMAP, POP3,
SMTP, NNTP news, a local calendar, contacts/WAB import, and legacy-mailbox import.

## The single most important constraint: accessibility

**The primary user is blind and uses the NVDA screen reader on Windows.**
Accessibility is not a feature — it is the top acceptance criterion. Every UI
change must remain fully operable by keyboard and intelligible to NVDA. Concrete
rules learned the hard way (do not regress these):

- **Email bodies render in `wx.html2.WebView` (Edge/WebView2), never
  `wx.html.HtmlWindow`.** HtmlWindow is custom-drawn and invisible to NVDA;
  WebView content is real HTML that NVDA reads in browse mode. See
  `ui/preview_panel.py`. It falls back to HtmlWindow only if no Edge backend
  exists.
- **`WebView2Loader.dll` must be bundled** in any PyInstaller build (the wx hook
  omits it). Without it the Edge backend silently disappears and the app falls
  back to the unreadable HtmlWindow. Handled in `corvid.spec`.
- Rendered pages carry a real `<!DOCTYPE html>` + `<title>` (else NVDA announces
  the URL, "about:blank") and use plain paragraphs, not tables, in headers (else
  NVDA announces "grouping / out of grouping").
- **Reading mode:** opening a message fills the window with just the email (tree
  and list hidden) so Tab can't escape it; **Escape returns to the list**. Escape
  is caught from inside the WebView via an injected `keydown` script that
  navigates to the `corvid:back` sentinel URL (vetoed in `_on_navigating`); a
  `postMessage` channel and a frame-level `EVT_CHAR_HOOK` are backups. See
  `main_frame._show_reading_only` / `_show_list_only` / `_right_keep`.
- **The message list is a native `wx.TreeCtrl`** (not a `ListCtrl`), so replies
  can nest under a collapsible conversation node and NVDA announces the level and
  expanded/collapsed state; **Left/Right collapse/expand** it natively. Each row
  (leaf or conversation summary) is one composed spoken line ("Unread, sender,
  subject. sent today at 6:48AM."), so NVDA speaks one clean sentence, not column
  cells. Item data is a tuple: `("msg", id)` for a message, `("grp", ids, newest)`
  for a conversation. Conversations start collapsed. See `presenters.row_speech` /
  `group_speech` and `main_frame._populate_groups`. Grouping is header-based
  (In-Reply-To/References → `domain/threads.py`), toggleable via **View → Group by
  Conversation** (`config.ui.group_by_conversation`). Keep it a native tree — a
  custom/owner-drawn tree would be invisible to NVDA.
- Custom-drawn widgets (e.g. `wx.adv.CalendarCtrl`) are invisible to NVDA — the
  calendar uses a WebView ARIA grid (`ui/calendar_html.py`). Use
  `ui/accessibility.py` helpers (`accessible_name`, MSAA name overrides) for
  composite controls.

When unsure whether a change is accessible, assume it isn't and verify with the
real app under NVDA before claiming it works.

## Architecture (layers, strict dependency direction)

`ui → service → domain ← infra`, wired by `app`.

- `domain/` — pure entities & business rules, no I/O.
- `infra/` — SQLite repositories, IMAP/POP3/SMTP/NNTP, parsing, OAuth,
  autodiscovery, DB migrations.
- `service/` — use-cases orchestrating infra for the UI (sync, send, search,
  accounts, messages, calendar…).
- `ui/` — wxPython views/dialogs/presenters (thin; untyped-widget layer).
- `app/` — bootstrap, paths, background job runner.

Key patterns: SQLite WAL with **thread-affine connections** (each worker thread
opens its own connection — never share a connection across threads; a common
crash source). **Forward-only migrations** in `infra/db/migrations.py`
(`MIGRATIONS` tuple, currently at **v7**; add the next version, never edit
applied ones). StrEnum everywhere; PEP 695 generics. FTS5 search with a LIKE
fallback. Presenters are pure and unit-tested (no wx import).

## Commands

Run from the repo root. (Shell is PowerShell on Windows; a Bash tool is also
available.)

```
python run.py              # run the app (real data in %LOCALAPPDATA%\Corvid)
python run.py --dev        # run against throwaway ./_devdata (safe for testing)

python -m pytest           # full test suite (must stay green)
python -m ruff check src tests
python -m mypy src         # strict; see exclusions below

pyinstaller corvid.spec                                   # -> dist/Corvid/Corvid.exe
"C:\Program Files (x86)\Inno Setup 6\ISCC.exe" packaging\corvid.iss  # -> dist/CorvidSetup-<ver>.exe
```

## Verification discipline (do this on every change)

1. `ruff check` + `mypy src` + `pytest` — all green, no exceptions.
2. For UI changes, headless-smoke with a short `wx.App` script
   (`PYTHONIOENCODING=utf-8 PYTHONPATH=src python -`) before relaunching.
3. Relaunch `python run.py --dev` and confirm it reaches "Corvid ready".
4. Never claim an accessibility fix works without the reasoning/verification to
   back it; prefer to let the user confirm under NVDA.

## Type-checking notes

`mypy` is strict, but two overrides exist in `pyproject.toml`: `wx.*`/`keyring.*`
are `ignore_missing_imports`, and **`corvid.ui.*` is `ignore_errors`** (wx
subclasses are untyped). So Pyright/IDE diagnostics in `ui/` (unused `_event`
args, `wx.Window` attribute access, tuple-vs-`wx.Size`) are expected noise —
`mypy src` passing is the source of truth. The core
(domain/infra/service) IS strictly typed; keep it that way.

## Packaging

- `packaging/corvid_gui.py` — frozen-app entry point (calls `ui.app.run()`).
- `corvid.spec` — PyInstaller one-folder build; bundles assets,
  `config.example.json`, and `WebView2Loader.dll`.
- `packaging/corvid.iss` — Inno Setup installer: **per-machine** install into
  `Program Files\ALS-Software\corvid` (requires admin/elevation),
  Start Menu + optional Desktop shortcut, and (if WebView2 is missing) it
  downloads Microsoft's Evergreen Bootstrapper on the wizard's download page and
  installs the runtime silently before finishing.
- App icon: `src/corvid/ui/assets/corvid.ico` (multi-res) + `corvid_*.png`.
- **Bump the version in all three places for a release:** `pyproject.toml`,
  `__version__` in `src/corvid/__init__.py`, and the `MyAppVersion` define in
  `packaging/corvid.iss`.

## Data locations

Per-user, resolved in `app/paths.py`. On Windows: config in
`%APPDATA%\ALS-Software\Corvid`, data (SQLite `corvid.sqlite3`, logs,
attachments) in `%LOCALAPPDATA%\ALS-Software\Corvid` — nested under the
`ALS-Software` publisher folder, matching the installer's Program Files layout.
`--dev` puts everything under `./_devdata`.

## Gotchas / house style

- Match surrounding code: comment density, naming, StrEnum, dataclasses.
- Notifications must read as **"Corvid"**, not "Python" (see `ui/app.py`
  `MSWUseToasts` / app name).
- Gmail: uses **app passwords** (OAuth code exists but is hidden — Google
  restricted-scope verification has no free path). `[Gmail]` and other Noselect
  IMAP folders are skipped in sync.
- `_devdata/`, `build/`, `dist/`, caches are throwaway; don't commit them.
- **Auto-update:** Help → Check for Updates queries the GitHub Releases API for
  `KamiKitsune420/corvid` (public repo). Layered as `domain/updates.py` (pure
  version/asset rules) → `infra/updates.py` (`GitHubUpdateClient`, injectable
  HTTP opener) → `service/updates.py` (`UpdateService`, repo constant
  `GITHUB_REPO`, version from `corvid.__version__`) → `ui/update_dialog.py`. It
  offers the `CorvidSetup-<ver>.exe` asset; a new release is published by tagging
  and attaching that installer.
- Git remote: `github.com/KamiKitsune420/corvid` (public). Commit/push only when
  asked.
