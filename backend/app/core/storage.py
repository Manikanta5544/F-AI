"""
Storage utility — uploads files to MinIO/S3 and returns storage key.

Existing files stored with the old key format ("uploads/{hash}.{ext}") are
handled in download_from_storage() in utils.py which strips the prefix.
"""
from __future__ import annotations

import hashlib
import mimetypes

import aioboto3

from app.core.config import settings


def compute_sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def make_storage_key(file_hash: str, filename: str) -> str:
    """
    Return a storage key WITHOUT the bucket prefix.
    Key format: "{sha256_hash}.{ext}"
    The bucket is always settings.MINIO_BUCKET_UPLOADS — specified separately.
    """
    ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else "bin"
    # Sanitize extension
    if not ext.isalnum() or len(ext) > 10:
        ext = "bin"
    return f"{file_hash}.{ext}"


def _s3_client():
    """Return an aioboto3 async context manager for S3/MinIO."""
    from aiobotocore.config import AioConfig

    endpoint = settings.MINIO_ENDPOINT.strip()
    if not endpoint.startswith(("http://", "https://")):
        endpoint = f"http{'s' if settings.MINIO_USE_SSL else ''}://{endpoint}"

    config = AioConfig(signature_version="s3v4")

    return aioboto3.Session().client(
        "s3",
        endpoint_url=endpoint,
        aws_access_key_id=settings.MINIO_ACCESS_KEY,
        aws_secret_access_key=settings.MINIO_SECRET_KEY,
        region_name=settings.MINIO_REGION,
        config=config,
    )


async def upload_file(
    file_bytes: bytes,
    filename: str,
    bucket: str | None = None,
) -> tuple[str, str]:
    """
    Upload bytes to MinIO. Returns (storage_key, file_hash).

    storage_key format: "{sha256}.{ext}" — no bucket prefix.
    Skips upload if object already exists (SHA-256 content-addressable dedup).

    Note: For backward compatibility with existing jobs that stored the old
    "uploads/{hash}.{ext}" format, download_from_storage() strips the prefix.
    """
    bucket = bucket or settings.MINIO_BUCKET_UPLOADS
    file_hash = compute_sha256(file_bytes)
    storage_key = make_storage_key(file_hash, filename)
    content_type = mimetypes.guess_type(filename)[0] or "application/octet-stream"

    async with _s3_client() as s3:
        try:
            # Skip upload if already present (content-addressable dedup)
            await s3.head_object(Bucket=bucket, Key=storage_key)
            return storage_key, file_hash
        except Exception:
            pass  # Object not found — proceed with upload

        await s3.put_object(
            Bucket=bucket,
            Key=storage_key,
            Body=file_bytes,
            ContentType=content_type,
        )

    return storage_key, file_hash


async def download_file(storage_key: str, bucket: str | None = None) -> bytes:
    """Download a file from MinIO by storage key."""
    bucket = bucket or settings.MINIO_BUCKET_UPLOADS
    # Handle both old format "uploads/{hash}.ext" and new format "{hash}.ext"
    key = storage_key
    bucket_prefix = f"{bucket}/"
    if key.startswith(bucket_prefix):
        key = key[len(bucket_prefix):]

    async with _s3_client() as s3:
        obj = await s3.get_object(Bucket=bucket, Key=key)
        return await obj["Body"].read()


async def ensure_buckets_exist() -> None:
    """Create required MinIO buckets if they don't exist. Called at startup."""
    buckets = [
        settings.MINIO_BUCKET_UPLOADS,
        settings.MINIO_BUCKET_PROCESSED,
        settings.MINIO_BUCKET_MODELS,
    ]
    async with _s3_client() as s3:
        for bucket in buckets:
            try:
                await s3.head_bucket(Bucket=bucket)
            except Exception:
                try:
                    await s3.create_bucket(Bucket=bucket)
                except Exception:
                    pass  # May already exist or creation failed (non-fatal)