from __future__ import annotations

import sys
import time
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from content_hub.settings import get_settings
from content_hub.storage.base import StorageConfigurationError, StorageError
from content_hub.storage.engine import create_media_storage_engine


def main() -> int:
    settings = get_settings()
    if not settings.storage_enabled:
        print(
            "Media storage is disabled; set CONTENT_HUB_STORAGE_ENABLED=true "
            "to run the S3-compatible check."
        )
        return 0

    try:
        engine = create_media_storage_engine(settings)
    except StorageConfigurationError as exc:
        print(f"Media storage is not configured: {exc}", file=sys.stderr)
        return 2
    if engine is None:
        print("Media storage engine is not configured.")
        return 0

    key = f"media-storage-check/{int(time.time())}.txt"
    content = b"content-hub-media-storage-check\n"
    try:
        result = engine.upload(
            key=key,
            content=content,
            content_type="text/plain",
        )
        assert result.storage_key == key
        assert engine.exists(key) is True
        print("S3-compatible storage upload/check passed.")
        print(f"storage_key={result.storage_key}")
        print(f"public_url={result.file_url}")
        engine.delete(key)
        print("S3-compatible storage cleanup passed.")
    except StorageError as exc:
        print(f"S3-compatible storage check failed: {exc}", file=sys.stderr)
        return 1

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
