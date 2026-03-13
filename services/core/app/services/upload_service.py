"""S3/Minio image upload service."""

from __future__ import annotations

import logging
import uuid
from io import BytesIO

import aioboto3

from app.core.config import settings

logger = logging.getLogger(__name__)

ALLOWED_CONTENT_TYPES = {"image/jpeg", "image/png", "image/webp"}
MAX_FILE_SIZE = 10 * 1024 * 1024  # 10 MB

_session = aioboto3.Session()


def _get_s3_config() -> dict:
    return {
        "endpoint_url": getattr(settings, "MINIO_ENDPOINT", "http://minio:9000"),
        "aws_access_key_id": getattr(settings, "MINIO_ACCESS_KEY", ""),
        "aws_secret_access_key": getattr(settings, "MINIO_SECRET_KEY", ""),
        "region_name": "us-east-1",
    }


def _get_bucket() -> str:
    return getattr(settings, "MINIO_BUCKET", "gastropilot-uploads")


def _get_public_url() -> str:
    return getattr(
        settings,
        "MINIO_PUBLIC_URL",
        f"{getattr(settings, 'MINIO_ENDPOINT', 'http://minio:9000')}/{_get_bucket()}",
    )


async def _ensure_bucket():
    async with _session.client("s3", **_get_s3_config()) as s3:
        try:
            await s3.head_bucket(Bucket=_get_bucket())
        except Exception:
            await s3.create_bucket(Bucket=_get_bucket())
            await s3.put_bucket_policy(
                Bucket=_get_bucket(),
                Policy=(
                    '{"Version":"2012-10-17","Statement":[{"Effect":"Allow",'
                    '"Principal":"*","Action":"s3:GetObject",'
                    f'"Resource":"arn:aws:s3:::{_get_bucket()}/*"'
                    "}]}"
                ),
            )


async def upload_image(
    file_data: bytes,
    content_type: str,
    prefix: str,
    tenant_id: str,
) -> str:
    """Upload image to Minio/S3 and return public URL."""
    if content_type not in ALLOWED_CONTENT_TYPES:
        raise ValueError(
            f"Unzulaessiger Dateityp: {content_type}. "
            f"Erlaubt: {', '.join(ALLOWED_CONTENT_TYPES)}"
        )

    if len(file_data) > MAX_FILE_SIZE:
        raise ValueError(
            f"Datei zu gross: {len(file_data) / 1024 / 1024:.1f} MB. "
            f"Maximum: {MAX_FILE_SIZE / 1024 / 1024:.0f} MB"
        )

    ext_map = {"image/jpeg": "jpg", "image/png": "png", "image/webp": "webp"}
    ext = ext_map.get(content_type, "jpg")
    filename = f"{prefix}/{tenant_id}/{uuid.uuid4().hex}.{ext}"

    await _ensure_bucket()

    async with _session.client("s3", **_get_s3_config()) as s3:
        await s3.upload_fileobj(
            BytesIO(file_data),
            _get_bucket(),
            filename,
            ExtraArgs={"ContentType": content_type},
        )

    public_url = f"{_get_public_url()}/{filename}"
    logger.info("Uploaded image: %s", public_url)
    return public_url
