"""Opaque, collision-resistant identifiers for non-database artifacts.

Database rows use integer primary keys. These string ids are for things that
live outside the database - on-disk attachment/message blob filenames, job
handles, and similar - where a stable, unguessable token is convenient.
"""

from __future__ import annotations

import secrets


def new_id(prefix: str = "") -> str:
    """Return a random hex token, optionally prefixed (e.g. ``new_id("job_")``)."""
    token = secrets.token_hex(8)
    return f"{prefix}{token}" if prefix else token
