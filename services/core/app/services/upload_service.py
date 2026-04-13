"""Image upload service with local filesystem and optional S3/Minio support."""

from __future__ import annotations

import logging
import uuid
from io import BytesIO
from pathlib import Path

from app.core.config import settings

logger = logging.getLogger(__name__)

ALLOWED_CONTENT_TYPES = {"image/jpeg", "image/png", "image/webp"}
MAX_FILE_SIZE = 10 * 1024 * 1024  # 10 MB


def _validate(file_data: bytes, content_type: str) -> str:
    """Validate file type and size, return file extension."""
    if content_type not in ALLOWED_CONTENT_TYPES:
        raise ValueError(
            f"Unzulaessiger Dateityp: {content_type}. Erlaubt: {', '.join(ALLOWED_CONTENT_TYPES)}"
        )
    if len(file_data) > MAX_FILE_SIZE:
        raise ValueError(
            f"Datei zu gross: {len(file_data) / 1024 / 1024:.1f} MB. "
            f"Maximum: {MAX_FILE_SIZE / 1024 / 1024:.0f} MB"
        )
    ext_map = {"image/jpeg": "jpg", "image/png": "png", "image/webp": "webp"}
    return ext_map.get(content_type, "jpg")


def _use_s3() -> bool:
    """Check if S3/Minio credentials are configured."""
    return bool(settings.MINIO_ACCESS_KEY and settings.MINIO_SECRET_KEY)


# ── Local filesystem backend ──────────────────────────────────────────────────

UPLOAD_DIR = Path(settings.UPLOAD_DIR) if hasattr(settings, "UPLOAD_DIR") else Path("/data/uploads")


async def _upload_local(file_data: bytes, content_type: str, prefix: str, tenant_id: str) -> str:
    ext = _validate(file_data, content_type)
    relative = f"{prefix}/{tenant_id}/{uuid.uuid4().hex}.{ext}"
    dest = UPLOAD_DIR / relative
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_bytes(file_data)

    public_base = settings.UPLOAD_PUBLIC_URL.rstrip("/")
    public_url = f"{public_base}/{relative}"
    logger.info("Uploaded image (local): %s", public_url)
    return public_url


# ── S3 / Minio backend ───────────────────────────────────────────────────────


async def _upload_s3(file_data: bytes, content_type: str, prefix: str, tenant_id: str) -> str:
    import aioboto3

    ext = _validate(file_data, content_type)
    filename = f"{prefix}/{tenant_id}/{uuid.uuid4().hex}.{ext}"

    bucket = settings.MINIO_BUCKET
    s3_config = {
        "endpoint_url": settings.MINIO_ENDPOINT,
        "aws_access_key_id": settings.MINIO_ACCESS_KEY,
        "aws_secret_access_key": settings.MINIO_SECRET_KEY,
        "region_name": "us-east-1",
    }

    session = aioboto3.Session()
    async with session.client("s3", **s3_config) as s3:
        # Ensure bucket exists
        try:
            await s3.head_bucket(Bucket=bucket)
        except Exception:
            await s3.create_bucket(Bucket=bucket)
            await s3.put_bucket_policy(
                Bucket=bucket,
                Policy=(
                    '{"Version":"2012-10-17","Statement":[{"Effect":"Allow",'
                    '"Principal":"*","Action":"s3:GetObject",'
                    f'"Resource":"arn:aws:s3:::{bucket}/*"'
                    "}]}"
                ),
            )

        await s3.upload_fileobj(
            BytesIO(file_data),
            bucket,
            filename,
            ExtraArgs={"ContentType": content_type},
        )

    public_url_base = settings.MINIO_PUBLIC_URL or (f"{settings.MINIO_ENDPOINT}/{bucket}")
    public_url = f"{public_url_base.rstrip('/')}/{filename}"
    logger.info("Uploaded image (s3): %s", public_url)
    return public_url


# ── Public API ────────────────────────────────────────────────────────────────


async def upload_image(
    file_data: bytes,
    content_type: str,
    prefix: str,
    tenant_id: str,
) -> str:
    """Upload image to configured backend (local or S3)."""
    if _use_s3():
        return await _upload_s3(file_data, content_type, prefix, tenant_id)
    return await _upload_local(file_data, content_type, prefix, tenant_id)
