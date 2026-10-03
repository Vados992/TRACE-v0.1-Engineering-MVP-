import hashlib
import os
import tempfile
from dataclasses import dataclass
from io import BytesIO
from pathlib import Path

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
        self.backend = settings.evidence_backend
        self.directory = Path(settings.evidence_directory).resolve()
        if self.backend == "filesystem":
            self.client = None
            self.bucket = "local"
            return
        self.client = Minio(
            settings.minio_endpoint,
            access_key=settings.minio_access_key,
            secret_key=settings.minio_secret_key,
            secure=settings.minio_secure,
        )
        self.bucket = settings.minio_bucket

    def ensure_bucket(self) -> None:
        if self.backend == "filesystem":
            self.directory.mkdir(parents=True, exist_ok=True)
            return
        if not self.client.bucket_exists(self.bucket):
            self.client.make_bucket(self.bucket)

    def _path(self, key: str) -> Path:
        def comparable(value):
            value = os.path.normcase(str(value))
            # Windows realpath may retain the extended prefix during concurrent path creation.
            if value.startswith("\\\\?\\unc\\"):
                value = "\\\\" + value[8:]
            elif value.startswith("\\\\?\\"):
                value = value[4:]
            return os.path.normpath(value)

        root = comparable(self.directory)
        path = (self.directory / key).resolve()
        try:
            inside = os.path.commonpath([root, comparable(path)]) == root
        except ValueError:
            inside = False
        if not inside:
            raise ValueError("invalid evidence key")
        return path

    def get_bytes(self, object_key: str, expected_hash: str | None = None) -> bytes:
        if self.backend == "filesystem":
            payload = self._path(object_key).read_bytes()
        else:
            response = self.client.get_object(self.bucket, object_key)
            try:
                payload = response.read()
            finally:
                response.close()
                response.release_conn()
        if expected_hash and hashlib.sha256(payload).hexdigest() != expected_hash:
            raise ValueError("evidence hash mismatch")
        return payload

    def check(self) -> None:
        self.ensure_bucket()
        if self.backend == "filesystem":
            with tempfile.TemporaryFile(dir=self.directory) as probe:
                probe.write(b"trace-readiness")
                probe.flush()
                os.fsync(probe.fileno())
        else:
            self.client.bucket_exists(self.bucket)

    def put_bytes(
        self,
        source_code: str,
        external_id: str,
        payload: bytes,
        media_type: str = "application/octet-stream",
    ) -> StoredArtifact:
        digest = hashlib.sha256(payload).hexdigest()
        safe_external = "".join(c if c.isalnum() or c in "._-" else "_" for c in external_id)[:180]
        safe_source = "".join(c for c in source_code.lower() if c.isalnum() or c == "_")
        if not safe_source:
            raise ValueError("invalid source code")
        key = f"{safe_source}/{digest[:2]}/{safe_external}/{digest}"
        self.ensure_bucket()
        if self.backend == "filesystem":
            path = self._path(key)
            path.parent.mkdir(parents=True, exist_ok=True)
            fd, temporary = tempfile.mkstemp(dir=path.parent, prefix=".write-")
            try:
                with os.fdopen(fd, "wb") as stream:
                    stream.write(payload)
                    stream.flush()
                    os.fsync(stream.fileno())
                try:
                    os.link(temporary, path)
                except FileExistsError:
                    self.get_bytes(key, digest)
                if os.name == "posix":
                    directory_fd = os.open(path.parent, os.O_RDONLY)
                    try:
                        os.fsync(directory_fd)
                    finally:
                        os.close(directory_fd)
            finally:
                Path(temporary).unlink(missing_ok=True)
            return StoredArtifact(key, digest, len(payload), media_type)
        try:
            self.client.stat_object(self.bucket, key)
            self.get_bytes(key, digest)
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
        if self.backend == "filesystem":
            return f"trace-evidence://local/{object_key}"
        return f"s3://{self.bucket}/{object_key}"
