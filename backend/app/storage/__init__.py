"""
Background response storage package.

Provides an abstract StorageBackend interface and concrete implementations:
  - LocalStorageBackend  — writes JSON files to the local filesystem
  - S3StorageBackend     — writes JSON objects to an S3-compatible bucket

Use `get_storage_backend()` to obtain the configured backend instance.
"""
from .base import StorageBackend, AsyncStorageBackend
from .local import LocalStorageBackend, AsyncLocalStorageBackend
from .s3 import S3StorageBackend, AsyncS3StorageBackend
from .factory import get_storage_backend, get_async_storage_backend

__all__ = [
    "StorageBackend", "AsyncStorageBackend",
    "LocalStorageBackend", "AsyncLocalStorageBackend",
    "S3StorageBackend", "AsyncS3StorageBackend",
    "get_storage_backend", "get_async_storage_backend",
]
