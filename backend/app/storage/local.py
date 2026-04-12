"""
Local filesystem storage backend.

Stores each payload as a plain JSON file under a configurable base directory.

Directory layout:
  {base_dir}/{response_id}/input.json
  {base_dir}/{response_id}/output.json
  {base_dir}/videos/{filename}         (binary video files)
"""
import os
from typing import Optional

from .base import StorageBackend


class LocalStorageBackend(StorageBackend):
    """
    StorageBackend implementation that writes files to the local filesystem.

    Configuration (via constructor or environment variables):
        base_dir — Root directory for all background response files.
                   Defaults to the value of the ``BACKGROUND_RESPONSE_STORAGE_DIR``
                   environment variable, or ``/tmp/model-link/background_responses``
                   if that variable is not set.
    """

    DEFAULT_BASE_DIR = "/tmp/model-link/background_responses"

    def __init__(self, base_dir: Optional[str] = None):
        self.base_dir = (
            base_dir
            or os.getenv("BACKGROUND_RESPONSE_STORAGE_DIR", self.DEFAULT_BASE_DIR)
        )

    def make_key(self, response_id: str, suffix: str) -> str:
        """Return the absolute file path for this response + suffix pair."""
        return os.path.join(self.base_dir, response_id, f"{suffix}.json")

    def write(self, key: str, content: str) -> None:
        """Write *content* to the file at *key*, creating parent dirs as needed."""
        os.makedirs(os.path.dirname(key), exist_ok=True)
        with open(key, "w", encoding="utf-8") as fh:
            fh.write(content)

    def read(self, key: str) -> Optional[str]:
        """Read and return the file content at *key*, or None if not found."""
        try:
            with open(key, "r", encoding="utf-8") as fh:
                return fh.read()
        except (FileNotFoundError, OSError):
            return None

    def write_binary(self, key: str, data: bytes, content_type: str = "application/octet-stream") -> str:
        """
        Write binary *data* to *key* on the local filesystem.

        Binary files are stored under ``{base_dir}/files/{key}``.
        The method returns a relative URL path ``/v1/files/{key}`` that the
        Flask gateway serves via the ``GET /v1/files/<path:filename>`` route.

        Args:
            key:          Filename (e.g. ``"vid_abc123.mp4"``).
            data:         Raw bytes.
            content_type: MIME type (unused for local storage, kept for API compat).

        Returns:
            URL path string, e.g. ``/v1/files/vid_abc123.mp4``.
        """
        files_dir = os.path.join(self.base_dir, "files")
        os.makedirs(files_dir, exist_ok=True)
        file_path = os.path.join(files_dir, key)
        with open(file_path, "wb") as fh:
            fh.write(data)
        return f"/v1/files/{key}"
