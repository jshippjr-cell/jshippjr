"""The disk store — exactly what the app did before the seam existed.

This is the DEFAULT, so an instance with nothing configured behaves as it always
has: bytes land in ``UPLOAD_DIR`` and are served straight off the filesystem.

It reports ``durable = False``, and that is the point. On Render this directory is
either ephemeral or a single-attach persistent disk that the Postgres cutover
removes — the deferred-work note is blunt about it: *"migrate uploads to object
storage first or the cutover destroys every client cut, master and stem."* The
SQLite mirror in ``_persist_upload`` is the net under this store, and it is only
worth its weight while this store is the one in use.
"""

from __future__ import annotations

import os
import shutil
from typing import Optional


class LocalObjectStore:
    durable = False

    def __init__(self, root: str):
        self.root = root
        try:
            os.makedirs(self.root, exist_ok=True)
        except OSError:
            pass

    def _path(self, key: str) -> Optional[str]:
        """Resolve a key inside the root, or None if it tries to escape.

        Traversal guard: the key must be a bare basename AND the resolved path must
        sit directly in the root. Both checks, because either alone has been fooled
        before (symlinks defeat the first, ".." defeats neither on its own).
        """
        base = os.path.basename(key or "")
        if not base or base != key:
            return None
        path = os.path.join(self.root, base)
        if os.path.realpath(path) != os.path.join(os.path.realpath(self.root), base):
            return None
        return path

    def put(self, key: str, data: bytes, content_type: str = "") -> bool:
        path = self._path(key)
        if path is None:
            return False
        try:
            os.makedirs(self.root, exist_ok=True)
            with open(path, "wb") as fh:
                fh.write(data)
            return True
        except OSError:
            return False

    def put_file(self, key: str, path: str, content_type: str = "") -> bool:
        """Copy on the filesystem — no bytes through Python."""
        dest = self._path(key)
        if dest is None:
            return False
        try:
            os.makedirs(self.root, exist_ok=True)
            if os.path.abspath(path) == os.path.abspath(dest):
                return True                 # already exactly where it belongs
            shutil.copyfile(path, dest)
            return True
        except OSError:
            return False

    def get(self, key: str) -> Optional[bytes]:
        path = self._path(key)
        if path is None or not os.path.exists(path):
            return None
        try:
            with open(path, "rb") as fh:
                return fh.read()
        except OSError:
            return None

    def exists(self, key: str) -> bool:
        path = self._path(key)
        return bool(path and os.path.exists(path))

    def size(self, key: str) -> Optional[int]:
        path = self._path(key)
        if path is None:
            return None
        try:
            return os.path.getsize(path)
        except OSError:
            return None

    def delete(self, key: str) -> bool:
        path = self._path(key)
        if path is None:
            return False
        try:
            os.remove(path)
            return True
        except OSError:
            return False

    def local_path(self, key: str) -> Optional[str]:
        path = self._path(key)
        return path if path and os.path.exists(path) else None

    def url(self, key: str, *, expires: int = 3600) -> Optional[str]:
        return None            # served from disk by the app, not by a URL
