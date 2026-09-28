from dataclasses import dataclass
from io import BytesIO
import hashlib

from minio import Minio
from minio.error import S3Error

from .settings import settings


@dataclass(frozen=True)
class StoredArtifact:
    object_key: str
    sha256: str
    byte_length: int
    media_type: str


class EvidenceStore:
    def __init__(self) -> None:
        self.client = Minio(
            settings.minio_endpoint,
            access_key=settings.minio_access_key,
            secret_key=settings.minio_secret_key,
            secure=settings.minio_secure,
        )
        self.bucket = settings.minio_bucket

    def ensure_bucket(self) -> None:
        if not self.client.bucket_exists(self.bucket):
            self.client.make_bucket(self.bucket)

    def put_bytes(
        self,
        source_code: str,
        external_id: str,
        payload: bytes,
        media_type: str = "application/octet-stream",
    ) -> StoredArtifact:
        digest = hashlib.sha256(payload).hexdigest()
        safe_external = "".join(
            c if c.isalnum() or c in "._-" else "_" for c in external_id
        )[:180]
        key = f"{source_code.lower()}/{digest[:2]}/{safe_external}/{digest}"
        self.ensure_bucket()
        try:
            self.client.stat_object(self.bucket, key)
        except S3Error as exc:
            if exc.code not in {"NoSuchKey", "NoSuchObject", "NoSuchBucket"}:
                raise
            self.client.put_object(
                self.bucket,
                key,
                BytesIO(payload),
                length=len(payload),
                content_type=media_type,
            )
        return StoredArtifact(
            object_key=key,
            sha256=digest,
            byte_length=len(payload),
            media_type=media_type,
        )

    def uri(self, object_key: str) -> str:
        return f"s3://{self.bucket}/{object_key}"
