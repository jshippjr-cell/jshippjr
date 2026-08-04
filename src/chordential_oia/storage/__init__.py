"""Where client media lives — the one seam.

``get_object_store()`` returns the backend chosen by ``CHORDENTIAL_STORAGE``
("local" | "s3"), defaulting to the local disk so an unconfigured instance behaves
exactly as it did before this seam existed. Same shape as the payment and mail
seams: null-ish default, env-selected real implementation, best-effort, never
raises into a request.

Why it exists (ADR-0043): uploads sat on a Render disk with, for most files, no
second copy — three write sites bypassed the mirroring helper whose own docstring
claimed to be "the single place that persists media". The Postgres cutover runbook
removes that disk. Measured on a seeded instance: four of five uploaded files had
exactly one copy.

The store is resolved per call rather than cached at import, because the tests and
the operator both need to change ``CHORDENTIAL_STORAGE`` without restarting a
process — and because a cached client is how a rotated credential goes unnoticed.
"""

from __future__ import annotations

import os

from .base import ObjectStore
from .local import LocalObjectStore

STORAGE_ENV = "CHORDENTIAL_STORAGE"


def get_object_store(local_root: str = "") -> ObjectStore:
    """The configured store. ``local_root`` is the disk directory the local backend
    uses (the caller passes ``UPLOAD_DIR``); it is ignored by remote backends."""
    choice = os.environ.get(STORAGE_ENV, "local").strip().lower()
    if choice in ("s3", "r2"):
        from .s3 import S3ObjectStore          # lazy — no boto3 unless selected
        store = S3ObjectStore()
        if store.configured:
            return store
        # Selected but half-configured: fall back to disk rather than silently
        # accepting uploads into a bucket that isn't there. The startup check in
        # app.py is what makes this loud instead of quiet.
    return LocalObjectStore(local_root or os.path.join(os.path.dirname(__file__), "uploads"))


def storage_status(local_root: str = "") -> dict:
    """What the operator needs to know at a glance: which store, and whether the
    bytes survive this machine. Surfaced at startup and on /healthz-adjacent
    checks so "we never turned it on" cannot be discovered by losing a master."""
    choice = os.environ.get(STORAGE_ENV, "local").strip().lower()
    store = get_object_store(local_root)
    return {
        "requested": choice,
        "active": "s3" if getattr(store, "durable", False) else "local",
        "durable": bool(getattr(store, "durable", False)),
        "misconfigured": choice in ("s3", "r2") and not getattr(store, "durable", False),
    }


__all__ = ["ObjectStore", "LocalObjectStore", "get_object_store", "storage_status",
           "STORAGE_ENV"]
