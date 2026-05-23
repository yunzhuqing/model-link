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

from .base import StorageBackend, AsyncStorageBackend

_backend: Optional[StorageBackend] = None
_async_backend: Optional[AsyncStorageBackend] = None


def get_storage_backend() -> StorageBackend:
    """Return the configured sync storage backend singleton."""
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
        raise ValueError(f"Unknown STORAGE_BACKEND {backend_type!r}. Supported values: 'local', 's3', 'cos'.")
    return _backend


def get_async_storage_backend() -> AsyncStorageBackend:
    """Return the configured async storage backend singleton."""
    global _async_backend
    if _async_backend is not None:
        return _async_backend
    backend_type = os.getenv("STORAGE_BACKEND", "local").lower().strip()
    if backend_type == "local":
        from .local import AsyncLocalStorageBackend
        _async_backend = AsyncLocalStorageBackend()
    elif backend_type == "s3" or backend_type == "cos":
        from .s3 import AsyncS3StorageBackend
        _async_backend = AsyncS3StorageBackend()
    else:
        raise ValueError(f"Unknown STORAGE_BACKEND {backend_type!r}. Supported values: 'local', 's3', 'cos'.")
    return _async_backend
