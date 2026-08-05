"""S3-compatible object storage — Cloudflare R2, AWS S3, MinIO, Backblaze B2.

One class for all of them because they speak the same API; only the endpoint
differs. R2 is the expected target (no egress fees, and the delivery package is
all egress).

Configuration, all ``CHORDENTIAL_S3_*``::

    CHORDENTIAL_STORAGE=s3
    CHORDENTIAL_S3_BUCKET=chordential-media
    CHORDENTIAL_S3_ENDPOINT=https://<account>.r2.cloudflarestorage.com   # omit for AWS
    CHORDENTIAL_S3_ACCESS_KEY=...
    CHORDENTIAL_S3_SECRET_KEY=...
    CHORDENTIAL_S3_REGION=auto                                          # R2 wants "auto"

``boto3`` is an optional dependency (the ``s3`` extra) and is imported lazily, so
an instance that never sets ``CHORDENTIAL_STORAGE=s3`` needs neither the package
nor the credentials.

Every method is best-effort in the same sense as the payment and mail seams: a
failure returns False/None and is logged by the caller's own honesty, never raised
into a request. Losing the bucket must degrade to "that file isn't available",
not to a 500 on the client's portal.
"""

from __future__ import annotations

import importlib.util
import os
from typing import Optional

_SDK_PRESENT: Optional[bool] = None


def sdk_available() -> bool:
    """Is ``boto3`` importable? Memoised — a deploy cannot gain a package without a
    restart, and this is on the per-request path."""
    global _SDK_PRESENT
    if _SDK_PRESENT is None:
        _SDK_PRESENT = importlib.util.find_spec("boto3") is not None
    return _SDK_PRESENT


class S3ObjectStore:
    durable = True

    def __init__(self):
        self.bucket = os.environ.get("CHORDENTIAL_S3_BUCKET", "").strip()
        self._endpoint = os.environ.get("CHORDENTIAL_S3_ENDPOINT", "").strip()
        self._region = os.environ.get("CHORDENTIAL_S3_REGION", "auto").strip()
        self._key = os.environ.get("CHORDENTIAL_S3_ACCESS_KEY", "").strip()
        self._secret = os.environ.get("CHORDENTIAL_S3_SECRET_KEY", "").strip()
        self._client = None

    @property
    def configured(self) -> bool:
        """Credentials **and** the SDK.

        The SDK check is not belt-and-braces; without it this class reports
        ``durable = True`` while being unable to move a byte, and `durable` is what
        tells `uploads.persist_upload` to SKIP the SQLite mirror. Measured: with
        credentials set and `boto3` missing, an uploaded master ended up with **zero**
        copies — not in the bucket, not on disk, not in the mirror — while the boot
        line announced "object storage active — uploads are durable." Reporting
        half-configured instead falls back to the disk, which is loud and lossless.

        The gap was real, not hypothetical: `render.yaml` installed
        ``.[web,gmail,ai,stripe,postgres]`` — no ``s3`` extra — so following the
        cutover runbook would have hit exactly this.
        """
        return bool(self.bucket and self._key and self._secret and sdk_available())

    def _c(self):
        """The boto3 client, built once. None when unusable — the caller falls back."""
        if self._client is not None:
            return self._client
        if not self.configured:
            return None
        try:
            import boto3                       # lazy: only this backend needs the SDK
            from botocore.config import Config
        except ImportError:
            return None
        try:
            self._client = boto3.client(
                "s3",
                endpoint_url=self._endpoint or None,
                region_name=self._region or None,
                aws_access_key_id=self._key,
                aws_secret_access_key=self._secret,
                # Retries are the SDK's job; the timeouts keep a wedged bucket from
                # holding a worker open while an operator waits on an upload.
                config=Config(retries={"max_attempts": 3, "mode": "standard"},
                              connect_timeout=5, read_timeout=60),
            )
        except Exception:
            self._client = None
        return self._client

    def put(self, key: str, data: bytes, content_type: str = "") -> bool:
        c = self._c()
        if c is None:
            return False
        try:
            extra = {"ContentType": content_type} if content_type else {}
            c.put_object(Bucket=self.bucket, Key=key, Body=data, **extra)
            return True
        except Exception:
            return False

    def get(self, key: str) -> Optional[bytes]:
        c = self._c()
        if c is None:
            return None
        try:
            return c.get_object(Bucket=self.bucket, Key=key)["Body"].read()
        except Exception:
            return None

    def exists(self, key: str) -> bool:
        c = self._c()
        if c is None:
            return False
        try:
            c.head_object(Bucket=self.bucket, Key=key)
            return True
        except Exception:
            return False

    def size(self, key: str) -> Optional[int]:
        """The object's Content-Length. Same HEAD ``exists`` makes, one field further
        in — so asking "is it a real file" costs no more than asking "is it there"."""
        c = self._c()
        if c is None:
            return None
        try:
            return int(c.head_object(Bucket=self.bucket, Key=key)["ContentLength"])
        except Exception:
            return None

    def delete(self, key: str) -> bool:
        c = self._c()
        if c is None:
            return False
        try:
            c.delete_object(Bucket=self.bucket, Key=key)
            return True
        except Exception:
            return False

    def local_path(self, key: str) -> Optional[str]:
        return None            # remote: served by presigned URL, not FileResponse

    def url(self, key: str, *, expires: int = 3600) -> Optional[str]:
        """A presigned GET. This is what makes Range/seek work on a 200 MB cut — the
        browser talks to the bucket directly and we never stream bytes through the app.
        Short-lived, and only minted after the caller's gate has already passed."""
        c = self._c()
        if c is None:
            return None
        try:
            return c.generate_presigned_url(
                "get_object", Params={"Bucket": self.bucket, "Key": key},
                ExpiresIn=int(expires))
        except Exception:
            return None
