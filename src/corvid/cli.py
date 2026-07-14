"""Command-line entry point.

Phase 1 ships a small operational CLI - enough to initialize, inspect, and
sanity-check an installation before the wxPython UI exists.

    corvid init      create config + database (idempotent)
    corvid info      show paths, schema version, and row counts
    corvid version   print the version
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from . import __version__
from .app.bootstrap import bootstrap
from .app.config import AppConfig
from .app.paths import AppPaths, default_paths, paths_for_root
from .errors import CorvidError
from .infra.db import current_version


def _resolve_paths(root: str | None) -> AppPaths:
    return paths_for_root(Path(root)) if root else default_paths()


def _cmd_version(_args: argparse.Namespace) -> int:
    print(f"corvid {__version__}")
    return 0


def _cmd_init(args: argparse.Namespace) -> int:
    paths = _resolve_paths(args.root).ensure()
    if not paths.config_file.exists():
        AppConfig.default().save(paths.config_file)
        print(f"Created config:   {paths.config_file}")
    else:
        print(f"Config exists:    {paths.config_file}")
    with bootstrap(paths) as ctx:
        print(f"Database ready:   {ctx.paths.database_file}")
        print(f"Schema version:   {current_version(ctx.db)}")
    return 0


def _cmd_info(args: argparse.Namespace) -> int:
    paths = _resolve_paths(args.root)
    if not paths.database_file.exists():
        print("No installation found. Run 'corvid init' first.", file=sys.stderr)
        return 1
    with bootstrap(paths) as ctx:
        def count(table: str) -> int:
            return int(ctx.db.execute(f"SELECT COUNT(*) AS n FROM {table}").fetchone()["n"])

        print(f"Config file:      {ctx.paths.config_file}")
        print(f"Database file:    {ctx.paths.database_file}")
        print(f"Log directory:    {ctx.paths.log_dir}")
        print(f"Schema version:   {current_version(ctx.db)}")
        print(f"Accounts:         {count('accounts')}")
        print(f"Messages:         {count('messages')}")
        print(f"Contacts:         {count('contacts')}")
        print(f"Drafts:           {count('drafts')}")
        print(f"Rules:            {count('rules')}")
    return 0


def _cmd_gui(args: argparse.Namespace) -> int:
    from .ui.app import run

    paths = _resolve_paths(args.root) if args.root else None
    return run(paths)


def _cmd_import(args: argparse.Namespace) -> int:
    from .infra.importers import SourceKind, build_importer
    from .service.factory import build_import_service

    paths = _resolve_paths(args.root)
    if not paths.database_file.exists():
        print("No installation found. Run 'corvid init' first.", file=sys.stderr)
        return 1
    source = Path(args.source)
    if not source.exists():
        print(f"Source not found: {source}", file=sys.stderr)
        return 1
    kind = SourceKind(args.kind) if args.kind else None
    with bootstrap(paths) as ctx:
        accounts = ctx.db.execute("SELECT id, email FROM accounts ORDER BY id").fetchall()
        if not accounts:
            print("No accounts exist. Add an account first.", file=sys.stderr)
            return 1
        if args.account is not None:
            account_id = args.account
        else:
            account_id = int(accounts[0]["id"])
        importer = build_importer(source, kind)
        service = build_import_service(ctx.db, ctx.paths.messages_dir)
        summary = service.import_into(account_id, importer)
        print(
            f"Imported {summary.imported} message(s) into {summary.folders} folder(s) "
            f"({summary.skipped} skipped, {summary.failed} failed)."
        )
        for name, count in summary.per_folder.items():
            print(f"  {name}: {count}")
    return 0


def _cmd_import_contacts(args: argparse.Namespace) -> int:
    from .infra.contact_importers import ContactSourceKind, build_contact_importer
    from .service.factory import build_contact_import_service

    paths = _resolve_paths(args.root)
    if not paths.database_file.exists():
        print("No installation found. Run 'corvid init' first.", file=sys.stderr)
        return 1
    source = Path(args.source)
    if not source.exists():
        print(f"Source not found: {source}", file=sys.stderr)
        return 1
    kind = ContactSourceKind(args.kind) if args.kind else None
    with bootstrap(paths) as ctx:
        importer = build_contact_importer(source, kind)
        service = build_contact_import_service(ctx.db)
        summary = service.import_contacts(importer)
        print(
            f"Imported {summary.imported} contact(s) "
            f"({summary.skipped} already present)."
        )
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="corvid", description="Corvid email client (CLI)")
    parser.add_argument(
        "--root",
        metavar="DIR",
        help="use a self-contained data directory instead of the default per-user location",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("version", help="print the version").set_defaults(func=_cmd_version)
    sub.add_parser("init", help="create config and database").set_defaults(func=_cmd_init)
    sub.add_parser("info", help="show installation details").set_defaults(func=_cmd_info)
    sub.add_parser("gui", help="launch the desktop UI").set_defaults(func=_cmd_gui)

    from .infra.importers import SourceKind

    imp = sub.add_parser("import", help="import a legacy/local mail store")
    imp.add_argument("source", help="path to an mbox file, Maildir, .eml directory, or .dbx file")
    imp.add_argument(
        "--kind",
        choices=[k.value for k in SourceKind],
        help="force the source kind instead of auto-detecting",
    )
    imp.add_argument("--account", type=int, help="account id to import into (default: first)")
    imp.set_defaults(func=_cmd_import)

    from .infra.contact_importers import ContactSourceKind

    impc = sub.add_parser("import-contacts", help="import contacts from an address book")
    impc.add_argument("source", help="path to a .vcf, .csv, .contact, .ldif, or .wab file")
    impc.add_argument(
        "--kind",
        choices=[k.value for k in ContactSourceKind],
        help="force the source kind instead of auto-detecting",
    )
    impc.set_defaults(func=_cmd_import_contacts)
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        result = args.func(args)
        return int(result)
    except CorvidError as exc:
        print(f"error: {exc.user_message}", file=sys.stderr)
        return 2


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
