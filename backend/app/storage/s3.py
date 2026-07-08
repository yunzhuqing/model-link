"""
S3-compatible object storage backend.

Stores each payload as an S3 object.  Works with AWS S3 and any S3-compatible
service (MinIO, GCS interop layer, Alibaba OSS, etc.).

Object key layout:
  {prefix}/{response_id}/input.json
  {prefix}/{response_id}/output.json

Required environment variables (when using this backend):
  STORAGE_S3_BUCKET      — bucket name (required)

Optional environment variables:
  STORAGE_S3_PREFIX      — object key prefix (default: "background_responses")
  STORAGE_S3_REGION      — AWS region (default: "us-east-1")
  STORAGE_S3_ENDPOINT    — custom endpoint URL for S3-compatible services
  AWS_ACCESS_KEY_ID      — AWS / provider access key (can use IAM role instead)
  AWS_SECRET_ACCESS_KEY  — AWS / provider secret key

boto3 must be installed: ``pip install boto3``
"""
import os
from typing import Optional

from .base import StorageBackend, AsyncStorageBackend


class S3StorageBackend(StorageBackend):
    """
    StorageBackend implementation that writes objects to an S3-compatible bucket.

    Args:
        bucket:       S3 bucket name.  Defaults to ``STORAGE_S3_BUCKET`` env var.
        prefix:       Object key prefix.  Defaults to ``STORAGE_S3_PREFIX`` env var
                      or ``"background_responses"``.
        region:       AWS region.  Defaults to ``STORAGE_S3_REGION`` or ``"us-east-1"``.
        endpoint_url: Custom endpoint for S3-compatible services.
                      Defaults to ``STORAGE_S3_ENDPOINT`` env var (None = AWS).
        access_key:   AWS access key ID.  Falls back to env / IAM role.
        secret_key:   AWS secret access key.  Falls back to env / IAM role.
    """

    def __init__(
        self,
        bucket: Optional[str] = None,
        prefix: Optional[str] = None,
        region: Optional[str] = None,
        endpoint_url: Optional[str] = None,
        access_key: Optional[str] = None,
        secret_key: Optional[str] = None,
    ):
        self.bucket = bucket or os.getenv("STORAGE_S3_BUCKET", "")
        if not self.bucket:
            raise ValueError(
                "S3StorageBackend requires a bucket name. "
                "Set STORAGE_S3_BUCKET env var or pass bucket= to the constructor."
            )
        self.prefix = prefix or os.getenv("STORAGE_S3_PREFIX", "background_responses")
        self.region = region or os.getenv("STORAGE_S3_REGION", "us-east-1")
        self.endpoint_url = endpoint_url or os.getenv("STORAGE_S3_ENDPOINT") or None
        self._access_key = access_key or os.getenv("ACCESS_KEY_ID")
        self._secret_key = secret_key or os.getenv("SECRET_ACCESS_KEY")

        # Lazy-initialise the boto3 client on first use to avoid import errors
        # on systems where boto3 is not installed.
        self._client = None

    def _get_client(self):
        """Return (and cache) a boto3 S3 client."""
        if self._client is None:
            try:
                import boto3
            except ImportError as exc:
                raise ImportError(
                    "boto3 is required for S3StorageBackend. "
                    "Install it with: pip install boto3"
                ) from exc

            kwargs: dict = {"region_name": self.region}
            if self.endpoint_url:
                kwargs["endpoint_url"] = self.endpoint_url
            if self._access_key and self._secret_key:
                kwargs["aws_access_key_id"] = self._access_key
                kwargs["aws_secret_access_key"] = self._secret_key

            self._client = boto3.client("s3", **kwargs)
        return self._client

    def make_key(self, response_id: str, suffix: str) -> str:
        """Return the S3 object key for this response + suffix pair."""
        return f"{self.prefix}/{response_id}/{suffix}.json"

    def write(self, key: str, content: str) -> None:
        """Upload *content* as a UTF-8 string to S3 object *key*."""
        client = self._get_client()
        client.put_object(
            Bucket=self.bucket,
            Key=key,
            Body=content.encode("utf-8"),
            ContentType="application/json",
        )

    def read(self, key: str) -> Optional[str]:
        """Download and return the S3 object at *key*, or None if not found."""
        client = self._get_client()
        try:
            response = client.get_object(Bucket=self.bucket, Key=key)
            return response["Body"].read().decode("utf-8")
        except client.exceptions.NoSuchKey:
            return None
        except Exception:  # pylint: disable=broad-except
            return None

    def url_for(self, key: str, expires_in: int = 7 * 24 * 3600) -> str:
        """
        Generate an accessible URL for an existing S3 object at *key*.

        If ``STORAGE_S3_PUBLIC_BASE_URL`` is set, returns a plain public URL.
        Otherwise returns a presigned URL valid for *expires_in* seconds.

        Args:
            key:        S3 object key.
            expires_in: Presigned URL validity in seconds (default 7 days).

        Returns:
            A URL string that can be used to download the object.
        """
        import os as _os
        public_base = _os.getenv("STORAGE_S3_PUBLIC_BASE_URL", "").rstrip("/")
        if public_base:
            return f"{public_base}/{key}"

        client = self._get_client()
        return client.generate_presigned_url(
            "get_object",
            Params={"Bucket": self.bucket, "Key": key},
            ExpiresIn=expires_in,
        )

    def write_binary(self, key: str, data: bytes, content_type: str = "application/octet-stream") -> str:
        """
        Upload binary *data* to S3 and return a presigned or public URL.

        See AsyncS3StorageBackend.write_binary for full documentation.
        """
        import os as _os
        s3_key = f"{self.prefix}/files/{key}"
        client = self._get_client()
        client.put_object(Bucket=self.bucket, Key=s3_key, Body=data, ContentType=content_type)
        public_base = _os.getenv("STORAGE_S3_PUBLIC_BASE_URL", "").rstrip("/")
        if public_base:
            return f"{public_base}/{s3_key}"
        presigned_url = client.generate_presigned_url(
            "get_object", Params={"Bucket": self.bucket, "Key": s3_key}, ExpiresIn=7 * 24 * 3600,
        )
        return presigned_url

    def read_binary(self, key_or_url: str) -> Optional[bytes]:
        """Retrieve binary data stored via write_binary() by S3 key."""
        s3_key = self._resolve_s3_key(key_or_url)
        client = self._get_client()
        try:
            response = client.get_object(Bucket=self.bucket, Key=s3_key)
            return response["Body"].read()
        except client.exceptions.NoSuchKey:
            return None
        except Exception:
            return None

    def delete_binary(self, key_or_url: str) -> bool:
        """
        Delete binary data stored via write_binary() from S3.

        Returns:
            True if the object was deleted, False if it was not found.
        """
        s3_key = self._resolve_s3_key(key_or_url)
        client = self._get_client()
        try:
            client.head_object(Bucket=self.bucket, Key=s3_key)
            client.delete_object(Bucket=self.bucket, Key=s3_key)
            return True
        except client.exceptions.NoSuchKey:
            return False
        except Exception:
            return False

    def _resolve_s3_key(self, key_or_url: str) -> str:
        """Resolve a key or URL to an S3 object key."""
        if key_or_url.startswith(f"{self.prefix}/files/"):
            return key_or_url
        return f"{self.prefix}/files/{key_or_url}"


# ═══════════════════════════════════════════════════════════════════════════════
# ── Async S3 Storage ──────────────────────────────────────────────────────────
# ═══════════════════════════════════════════════════════════════════════════════


class AsyncS3StorageBackend(AsyncStorageBackend):
    """Async S3-compatible storage using aioboto3."""

    def __init__(
        self,
        bucket: Optional[str] = None,
        prefix: Optional[str] = None,
        region: Optional[str] = None,
        endpoint_url: Optional[str] = None,
        access_key: Optional[str] = None,
        secret_key: Optional[str] = None,
    ):
        self.bucket = bucket or os.getenv("STORAGE_S3_BUCKET", "")
        if not self.bucket:
            raise ValueError(
                "AsyncS3StorageBackend requires a bucket name. "
                "Set STORAGE_S3_BUCKET env var or pass bucket= to the constructor."
            )
        self.prefix = prefix or os.getenv("STORAGE_S3_PREFIX", "background_responses")
        self.region = region or os.getenv("STORAGE_S3_REGION", "us-east-1")
        self.endpoint_url = endpoint_url or os.getenv("STORAGE_S3_ENDPOINT") or None
        self._access_key = access_key or os.getenv("ACCESS_KEY_ID")
        self._secret_key = secret_key or os.getenv("SECRET_ACCESS_KEY")
        self._session = None

    def _get_session(self):
        """Return (and cache) an aioboto3 Session."""
        if self._session is None:
            try:
                import aioboto3
            except ImportError as exc:
                raise ImportError(
                    "aioboto3 is required for AsyncS3StorageBackend. "
                    "Install it with: pip install aioboto3"
                ) from exc
            self._session = aioboto3.Session()
        return self._session

    def _client_kwargs(self) -> dict:
        kwargs: dict = {"region_name": self.region}
        if self.endpoint_url:
            kwargs["endpoint_url"] = self.endpoint_url
        if self._access_key and self._secret_key:
            kwargs["aws_access_key_id"] = self._access_key
            kwargs["aws_secret_access_key"] = self._secret_key
        return kwargs

    def make_key(self, response_id: str, suffix: str) -> str:
        return f"{self.prefix}/{response_id}/{suffix}.json"

    async def write(self, key: str, content: str) -> None:
        session = self._get_session()
        async with session.client("s3", **self._client_kwargs()) as client:
            await client.put_object(
                Bucket=self.bucket, Key=key, Body=content.encode("utf-8"),
                ContentType="application/json",
            )

    async def read(self, key: str) -> Optional[str]:
        session = self._get_session()
        async with session.client("s3", **self._client_kwargs()) as client:
            try:
                response = await client.get_object(Bucket=self.bucket, Key=key)
                body = await response["Body"].read()
                return body.decode("utf-8")
            except client.exceptions.NoSuchKey:
                return None
            except Exception:
                return None

    def url_for(self, key: str, expires_in: int = 7 * 24 * 3600) -> str:
        """Generate a public or presigned URL (sync — uses sync client for presigning)."""
        public_base = os.getenv("STORAGE_S3_PUBLIC_BASE_URL", "").rstrip("/")
        if public_base:
            return f"{public_base}/{key}"
        # Presigning requires a sync client — use the sync backend temporarily
        import boto3
        kwargs: dict = {"region_name": self.region}
        if self.endpoint_url:
            kwargs["endpoint_url"] = self.endpoint_url
        if self._access_key and self._secret_key:
            kwargs["aws_access_key_id"] = self._access_key
            kwargs["aws_secret_access_key"] = self._secret_key
        client = boto3.client("s3", **kwargs)
        return client.generate_presigned_url(
            "get_object", Params={"Bucket": self.bucket, "Key": key}, ExpiresIn=expires_in,
        )

    async def write_binary(self, key: str, data: bytes, content_type: str = "application/octet-stream") -> str:
        s3_key = f"{self.prefix}/files/{key}"
        session = self._get_session()
        async with session.client("s3", **self._client_kwargs()) as client:
            await client.put_object(Bucket=self.bucket, Key=s3_key, Body=data, ContentType=content_type)
        public_base = os.getenv("STORAGE_S3_PUBLIC_BASE_URL", "").rstrip("/")
        if public_base:
            return f"{public_base}/{s3_key}"
        return self.url_for(s3_key)

    def _resolve_s3_key(self, key_or_url: str) -> str:
        """Resolve a key or URL to an S3 object key."""
        if key_or_url.startswith(f"{self.prefix}/files/"):
            return key_or_url
        return f"{self.prefix}/files/{key_or_url}"

    async def read_binary(self, key_or_url: str) -> Optional[bytes]:
        s3_key = self._resolve_s3_key(key_or_url)
        session = self._get_session()
        async with session.client("s3", **self._client_kwargs()) as client:
            try:
                response = await client.get_object(Bucket=self.bucket, Key=s3_key)
                return await response["Body"].read()
            except client.exceptions.NoSuchKey:
                return None
            except Exception:
                return None

    async def delete_binary(self, key_or_url: str) -> bool:
        """
        Delete binary data stored via write_binary() from S3 (async).

        Returns:
            True if the object was deleted, False if it was not found.
        """
        s3_key = self._resolve_s3_key(key_or_url)
        session = self._get_session()
        async with session.client("s3", **self._client_kwargs()) as client:
            try:
                await client.head_object(Bucket=self.bucket, Key=s3_key)
                await client.delete_object(Bucket=self.bucket, Key=s3_key)
                return True
            except client.exceptions.NoSuchKey:
                return False
            except Exception:
                return False
