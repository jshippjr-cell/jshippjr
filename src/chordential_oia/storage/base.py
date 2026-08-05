"""What a place to keep client media has to be able to do.

Deliberately few verbs. Uploads are written once and read many times; anything
richer (listing, copying, lifecycle rules) belongs to whoever administers the
bucket, not to the app.
"""

from __future__ import annotations

from typing import Optional, Protocol


class ObjectStore(Protocol):
    """A content-addressed-enough store: the app supplies the key (a safe basename)."""

    #: True when the bytes survive the loss of this machine's disk. The DB mirror
    #: exists ONLY to cover a store that isn't; see ``_persist_upload``.
    durable: bool

    def put(self, key: str, data: bytes, content_type: str = "") -> bool:
        """Store ``data`` under ``key``. Returns True on success. Never raises —
        a storage backend that throws must not take an upload request down with it."""
        ...

    def get(self, key: str) -> Optional[bytes]:
        """The bytes, or None when the key isn't there."""
        ...

    def exists(self, key: str) -> bool:
        ...

    def size(self, key: str) -> Optional[int]:
        """Bytes stored under ``key``, or None when it isn't there.

        Separate from ``exists`` because existence is not playability: a zero-byte
        object is present, passes every existence check, and plays as silence. The
        audit on /settings/storage reports this so "the file is there" and "the file
        is a file" stop being the same claim. Cheap on every backend — a stat, or the
        Content-Length a HEAD already returns.
        """
        ...

    def delete(self, key: str) -> bool:
        ...

    def local_path(self, key: str) -> Optional[str]:
        """A real filesystem path when one exists, else None.

        The serving route uses this for its fast path: ``FileResponse`` on a real
        file gives native Range/seek, which is what makes a 200 MB cut scrub in the
        review player. A remote store returns None and is served by URL instead.
        """
        ...

    def url(self, key: str, *, expires: int = 3600) -> Optional[str]:
        """A time-limited URL the browser can fetch directly, or None if the store
        can't issue one. Only ever handed out *after* the caller's own gate (the
        payment gate, the share token) has passed."""
        ...
