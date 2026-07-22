import base64
from hashlib import sha256
from pathlib import Path
from typing import Any
from urllib.parse import unquote, urlparse
from uuid import uuid4

from botocore.exceptions import ClientError
from vtv_schemas.jobs import AssetRef
from vtv_schemas.uploads import PresignedPart, UploadPart

from .adapter import BackendMultipart, StoredObject, UploadIntegrityError


class S3ObjectStore:
    def __init__(self, client: Any, bucket: str, presign_ttl_seconds: int = 3600) -> None:
        self._client = client
        self._bucket = bucket
        self._presign_ttl_seconds = presign_ttl_seconds

    def uri_for(self, object_key: str) -> str:
        return f"s3://{self._bucket}/{object_key}"

    def create_multipart(
        self,
        *,
        object_key: str,
        content_type: str,
        part_count: int,
    ) -> BackendMultipart:
        response = self._client.create_multipart_upload(
            Bucket=self._bucket,
            Key=object_key,
            ContentType=content_type,
            Metadata={"immutable": "true"},
            ChecksumAlgorithm="SHA256",
        )
        provider_upload_id = response["UploadId"]
        return BackendMultipart(
            provider_upload_id=provider_upload_id,
            parts=self.presign_parts(
                object_key=object_key,
                provider_upload_id=provider_upload_id,
                part_numbers=list(range(1, part_count + 1)),
            ),
        )

    def presign_parts(
        self,
        *,
        object_key: str,
        provider_upload_id: str,
        part_numbers: list[int],
    ) -> list[PresignedPart]:
        return [
            PresignedPart(
                part_number=number,
                url=self._client.generate_presigned_url(
                    "upload_part",
                    Params={
                        "Bucket": self._bucket,
                        "Key": object_key,
                        "UploadId": provider_upload_id,
                        "PartNumber": number,
                    },
                    ExpiresIn=self._presign_ttl_seconds,
                ),
            )
            for number in part_numbers
        ]

    def complete_multipart(
        self,
        *,
        object_key: str,
        provider_upload_id: str,
        parts: list[UploadPart],
    ) -> StoredObject:
        if any(part.checksum_sha256 is None for part in parts):
            raise UploadIntegrityError("S3 multipart completion requires every part SHA-256")
        self._client.complete_multipart_upload(
            Bucket=self._bucket,
            Key=object_key,
            UploadId=provider_upload_id,
            MultipartUpload={
                "Parts": [
                    {
                        "ETag": part.etag,
                        "PartNumber": part.part_number,
                        "ChecksumSHA256": part.checksum_sha256,
                    }
                    for part in parts
                ]
            },
        )
        head = self._client.head_object(
            Bucket=self._bucket,
            Key=object_key,
            ChecksumMode="ENABLED",
        )
        if int(head["ContentLength"]) <= 0:
            raise UploadIntegrityError("stored object is empty")
        checksum = head.get("ChecksumSHA256")
        return StoredObject(
            size_bytes=int(head["ContentLength"]),
            content_type=head.get("ContentType", "application/octet-stream"),
            checksum_sha256=checksum,
        )

    def abort_multipart(self, *, object_key: str, provider_upload_id: str) -> None:
        self._client.abort_multipart_upload(
            Bucket=self._bucket,
            Key=object_key,
            UploadId=provider_upload_id,
        )

    def download_file(
        self,
        *,
        object_uri: str,
        destination: Path,
        expected_sha256: str,
        expected_size_bytes: int,
    ) -> Path:
        key = self._key_from_uri(object_uri)
        destination.parent.mkdir(parents=True, exist_ok=True)
        temporary = destination.with_name(f".{destination.name}.{uuid4().hex}.part")
        digest = sha256()
        size = 0
        try:
            response = self._client.get_object(Bucket=self._bucket, Key=key)
            body = response["Body"]
            try:
                with temporary.open("wb") as handle:
                    while chunk := body.read(4 * 1024 * 1024):
                        handle.write(chunk)
                        digest.update(chunk)
                        size += len(chunk)
            finally:
                body.close()
            if size != expected_size_bytes:
                raise UploadIntegrityError(
                    "downloaded object size mismatch: "
                    f"expected {expected_size_bytes}, actual {size}"
                )
            if digest.hexdigest() != expected_sha256:
                raise UploadIntegrityError("downloaded object SHA-256 mismatch")
            temporary.replace(destination)
        finally:
            temporary.unlink(missing_ok=True)
        return destination

    def upload_file(
        self, *, source: Path, object_key: str, content_type: str
    ) -> AssetRef:
        if not source.is_file():
            raise UploadIntegrityError(f"worker output does not exist: {source}")
        digest = sha256()
        size = 0
        with source.open("rb") as handle:
            while chunk := handle.read(4 * 1024 * 1024):
                digest.update(chunk)
                size += len(chunk)
        if size <= 0:
            raise UploadIntegrityError("worker output is empty")
        checksum_hex = digest.hexdigest()
        checksum_base64 = base64.b64encode(digest.digest()).decode("ascii")
        try:
            with source.open("rb") as handle:
                self._client.put_object(
                    Bucket=self._bucket,
                    Key=object_key,
                    Body=handle,
                    ContentLength=size,
                    ContentType=content_type,
                    ChecksumSHA256=checksum_base64,
                    Metadata={"immutable": "true", "sha256": checksum_hex},
                    IfNoneMatch="*",
                )
        except ClientError as exc:
            code = str(exc.response.get("Error", {}).get("Code", ""))
            if code not in {"PreconditionFailed", "412"}:
                raise
            existing = self._client.head_object(Bucket=self._bucket, Key=object_key)
            metadata = existing.get("Metadata", {})
            if (
                int(existing.get("ContentLength", -1)) != size
                or metadata.get("sha256") != checksum_hex
            ):
                raise UploadIntegrityError(
                    "immutable object key already contains different content"
                ) from exc
        return AssetRef(
            uri=self.uri_for(object_key),
            sha256=checksum_hex,
            media_type=content_type,
            size_bytes=size,
        )

    def _key_from_uri(self, object_uri: str) -> str:
        parsed = urlparse(object_uri)
        if parsed.scheme != "s3" or parsed.netloc != self._bucket:
            raise UploadIntegrityError("object URI does not belong to configured S3 bucket")
        key = unquote(parsed.path.lstrip("/"))
        if not key:
            raise UploadIntegrityError("object URI has an empty key")
        return key
