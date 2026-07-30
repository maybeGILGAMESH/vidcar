"""S3 multipart abstraction plus an infrastructure-free in-memory implementation."""
from __future__ import annotations

import hashlib
import io
from dataclasses import dataclass, field
from typing import BinaryIO, Protocol
from uuid import uuid4


class ObjectNotFound(FileNotFoundError):
    pass


class ObjectStorage(Protocol):
    def create_multipart(self, bucket: str, key: str, content_type: str, metadata: dict[str, str]) -> str: ...
    def presign_part(self, bucket: str, key: str, upload_id: str, part_number: int, expires: int) -> str: ...
    def complete_multipart(
        self, bucket: str, key: str, upload_id: str, parts: list[dict[str, object]]
    ) -> dict[str, object]: ...
    def head(self, bucket: str, key: str) -> dict[str, object]: ...
    def iter_bytes(self, bucket: str, key: str, chunk_size: int = 1024 * 1024): ...
    def presign_get(self, bucket: str, key: str, expires: int) -> str: ...


class Boto3ObjectStorage:
    def __init__(
        self,
        client=None,
        public_endpoint_url: str | None = None,
        **client_kwargs,
    ):
        if client is None:
            import boto3
            from botocore.config import Config

            config = Config(signature_version="s3v4", s3={"addressing_style": "path"})
            client = boto3.client("s3", config=config, **client_kwargs)
        self.client = client
        # Presign with the browser-reachable endpoint so Host/path match the signed URL.
        public = public_endpoint_url or client_kwargs.get("endpoint_url")
        if public and public != client_kwargs.get("endpoint_url"):
            import boto3
            from botocore.config import Config

            public_kwargs = dict(client_kwargs)
            public_kwargs["endpoint_url"] = public
            self.presign_client = boto3.client(
                "s3",
                config=Config(signature_version="s3v4", s3={"addressing_style": "path"}),
                **public_kwargs,
            )
        else:
            self.presign_client = client

    def create_multipart(self, bucket, key, content_type, metadata):
        result = self.client.create_multipart_upload(
            Bucket=bucket, Key=key, ContentType=content_type, Metadata=metadata
        )
        return result["UploadId"]

    def presign_part(self, bucket, key, upload_id, part_number, expires):
        return self.presign_client.generate_presigned_url(
            "upload_part",
            Params={"Bucket": bucket, "Key": key, "UploadId": upload_id, "PartNumber": part_number},
            ExpiresIn=expires,
        )

    def complete_multipart(self, bucket, key, upload_id, parts):
        return self.client.complete_multipart_upload(
            Bucket=bucket, Key=key, UploadId=upload_id, MultipartUpload={"Parts": parts}
        )

    def put_object(self, bucket: str, key: str, data: bytes, metadata: dict[str, str] | None = None) -> None:
        kwargs: dict = {"Bucket": bucket, "Key": key, "Body": data}
        if metadata:
            kwargs["Metadata"] = metadata
        self.client.put_object(**kwargs)

    def head(self, bucket, key):
        try:
            return self.client.head_object(Bucket=bucket, Key=key)
        except self.client.exceptions.NoSuchKey as exc:
            raise ObjectNotFound(key) from exc

    def iter_bytes(self, bucket, key, chunk_size=1024 * 1024):
        body = self.client.get_object(Bucket=bucket, Key=key)["Body"]
        while chunk := body.read(chunk_size):
            yield chunk

    def presign_get(self, bucket, key, expires):
        return self.presign_client.generate_presigned_url(
            "get_object", Params={"Bucket": bucket, "Key": key}, ExpiresIn=expires
        )


@dataclass
class MemoryObjectStorage:
    """Deterministic test adapter. ``put_part`` is intentionally non-protocol test support."""

    objects: dict[tuple[str, str], bytes] = field(default_factory=dict)
    metadata: dict[tuple[str, str], dict[str, str]] = field(default_factory=dict)
    uploads: dict[str, dict] = field(default_factory=dict)

    def create_multipart(self, bucket, key, content_type, metadata):
        if (bucket, key) in self.objects:
            raise FileExistsError(f"immutable object already exists: {bucket}/{key}")
        upload_id = str(uuid4())
        self.uploads[upload_id] = {
            "bucket": bucket,
            "key": key,
            "parts": {},
            "metadata": dict(metadata),
            "content_type": content_type,
        }
        return upload_id

    def presign_part(self, bucket, key, upload_id, part_number, expires):
        return f"memory://{bucket}/{key}?uploadId={upload_id}&partNumber={part_number}"

    def put_part(self, upload_id: str, part_number: int, data: bytes) -> str:
        upload = self.uploads[upload_id]
        upload["parts"][part_number] = data
        return hashlib.md5(data, usedforsecurity=False).hexdigest()

    def put_object(self, bucket: str, key: str, data: bytes, metadata: dict[str, str] | None = None) -> None:
        if (bucket, key) in self.objects:
            raise FileExistsError(f"immutable object already exists: {bucket}/{key}")
        self.objects[(bucket, key)] = data
        self.metadata[(bucket, key)] = metadata or {}

    def complete_multipart(self, bucket, key, upload_id, parts):
        upload = self.uploads.pop(upload_id)
        if upload["bucket"] != bucket or upload["key"] != key:
            raise ValueError("multipart target mismatch")
        data = b"".join(upload["parts"][int(part["PartNumber"])] for part in parts)
        self.put_object(bucket, key, data, upload["metadata"])
        return {"Bucket": bucket, "Key": key, "ETag": hashlib.md5(data, usedforsecurity=False).hexdigest()}

    def head(self, bucket, key):
        try:
            data = self.objects[(bucket, key)]
        except KeyError as exc:
            raise ObjectNotFound(key) from exc
        return {
            "ContentLength": len(data),
            "Metadata": self.metadata.get((bucket, key), {}),
            "ChecksumSHA256": hashlib.sha256(data).hexdigest(),
        }

    def iter_bytes(self, bucket, key, chunk_size=1024 * 1024):
        try:
            stream = io.BytesIO(self.objects[(bucket, key)])
        except KeyError as exc:
            raise ObjectNotFound(key) from exc
        while chunk := stream.read(chunk_size):
            yield chunk

    def presign_get(self, bucket, key, expires):
        self.head(bucket, key)
        return f"memory://{bucket}/{key}?download=1"
