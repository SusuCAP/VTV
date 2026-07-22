from typing import Any

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
            parts=[
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
                for number in range(1, part_count + 1)
            ],
        )

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
