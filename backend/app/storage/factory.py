"""
Storage backend factory.

Reads the ``STORAGE_BACKEND`` environment variable to determine which
concrete StorageBackend to instantiate:

  STORAGE_BACKEND=local  (default) — LocalStorageBackend
  STORAGE_BACKEND=s3               — S3StorageBackend

The factory returns a module-level singleton so the same backend instance
is shared across all requests in a single process.
"""
import os
from typing import Optional

from .base import StorageBackend

_backend: Optional[StorageBackend] = None


def get_storage_backend() -> StorageBackend:
    """
    Return the configured storage backend singleton.

    The backend type is determined by the ``STORAGE_BACKEND`` environment
    variable (default: ``"local"``).  The singleton is created on first call
    and reused for the lifetime of the process.

    Supported values:
        ``local`` — LocalStorageBackend (writes to the local filesystem)
        ``s3``    — S3StorageBackend   (writes to an S3-compatible bucket)

    Returns:
        A StorageBackend instance.

    Raises:
        ValueError: If an unknown backend type is configured.
    """
    global _backend
    if _backend is not None:
        return _backend

    backend_type = os.getenv("STORAGE_BACKEND", "local").lower().strip()

    if backend_type == "local":
        from .local import LocalStorageBackend
        _backend = LocalStorageBackend()
    elif backend_type == "s3" or backend_type == "cos":
        from .s3 import S3StorageBackend
        _backend = S3StorageBackend()
    else:
        raise ValueError(
            f"Unknown STORAGE_BACKEND {backend_type!r}. "
            "Supported values: 'local', 's3', 'cos'."
        )

    return _backend
