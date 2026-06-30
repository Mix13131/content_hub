from __future__ import annotations

from typing import Any
from urllib.parse import quote

from content_hub.storage.base import (
    StorageConfigurationError,
    StorageError,
    StorageResult,
)


class S3CompatibleStorage:
    provider = "s3"

    def __init__(
        self,
        *,
        endpoint_url: str | None,
        access_key_id: str | None,
        secret_access_key: str | None,
        bucket: str | None,
        region: str | None = None,
        public_base_url: str | None = None,
        client: Any | None = None,
    ) -> None:
        self.endpoint_url = self._required(endpoint_url, "CONTENT_HUB_S3_ENDPOINT_URL")
        self.bucket = self._required(bucket, "CONTENT_HUB_S3_BUCKET")
        self.public_base_url = self._optional(public_base_url)
        self._client = client or self._build_client(
            access_key_id=access_key_id,
            secret_access_key=secret_access_key,
            region=region,
        )

    def upload(
        self,
        *,
        key: str,
        content: bytes,
        content_type: str | None = None,
    ) -> StorageResult:
        put_object_kwargs: dict[str, Any] = {
            "Bucket": self.bucket,
            "Key": key,
            "Body": content,
        }
        if content_type:
            put_object_kwargs["ContentType"] = content_type
        try:
            self._client.put_object(**put_object_kwargs)
        except Exception as exc:
            raise StorageError("S3-compatible upload failed.") from exc
        return StorageResult(
            storage_key=key,
            file_url=self.public_url(key),
            provider=self.provider,
            content_type=content_type,
            size_bytes=len(content),
        )

    def delete(self, key: str) -> None:
        try:
            self._client.delete_object(Bucket=self.bucket, Key=key)
        except Exception as exc:
            raise StorageError("S3-compatible delete failed.") from exc

    def exists(self, key: str) -> bool:
        try:
            self._client.head_object(Bucket=self.bucket, Key=key)
        except Exception as exc:
            error = getattr(exc, "response", {}).get("Error", {})
            status_code = getattr(exc, "response", {}).get("ResponseMetadata", {}).get(
                "HTTPStatusCode"
            )
            error_code = str(error.get("Code", ""))
            if status_code == 404 or error_code in {"404", "NoSuchKey", "NotFound"}:
                return False
            raise StorageError("S3-compatible exists check failed.") from exc
        return True

    def public_url(self, key: str) -> str:
        encoded_key = quote(key.lstrip("/"), safe="/")
        if self.public_base_url:
            return f"{self.public_base_url.rstrip('/')}/{encoded_key}"
        return (
            f"{self.endpoint_url.rstrip('/')}/"
            f"{quote(self.bucket, safe='')}/{encoded_key}"
        )

    def _build_client(
        self,
        *,
        access_key_id: str | None,
        secret_access_key: str | None,
        region: str | None,
    ) -> Any:
        access_key = self._required(
            access_key_id,
            "CONTENT_HUB_S3_ACCESS_KEY_ID",
        )
        secret_key = self._required(
            secret_access_key,
            "CONTENT_HUB_S3_SECRET_ACCESS_KEY",
        )
        try:
            import boto3
        except ImportError as exc:
            raise StorageConfigurationError("boto3 is required for S3 storage.") from exc

        client_kwargs: dict[str, Any] = {
            "service_name": "s3",
            "endpoint_url": self.endpoint_url,
            "aws_access_key_id": access_key,
            "aws_secret_access_key": secret_key,
        }
        clean_region = self._optional(region)
        if clean_region:
            client_kwargs["region_name"] = clean_region
        return boto3.client(**client_kwargs)

    def _required(self, value: str | None, env_name: str) -> str:
        clean_value = self._optional(value)
        if not clean_value:
            raise StorageConfigurationError(f"{env_name} is required for S3 storage.")
        return clean_value

    def _optional(self, value: str | None) -> str | None:
        if value is None:
            return None
        clean_value = value.strip()
        return clean_value or None
