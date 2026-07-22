from hashlib import sha256
from io import BytesIO
from pathlib import Path

import pytest
from botocore.exceptions import ClientError
from vtv_schemas.uploads import UploadPart
from vtv_storage import UploadIntegrityError
from vtv_storage.s3 import S3ObjectStore


class FakeS3Client:
    def __init__(self) -> None:
        self.completed: dict | None = None
        self.objects: dict[str, bytes] = {"inputs/source.bin": b"source bytes"}
        self.put: dict | None = None

    def create_multipart_upload(self, **kwargs: object) -> dict[str, str]:
        assert kwargs["Metadata"] == {"immutable": "true"}
        assert kwargs["ChecksumAlgorithm"] == "SHA256"
        return {"UploadId": "provider-123"}

    def generate_presigned_url(
        self, operation: str, Params: dict, ExpiresIn: int
    ) -> str:
        assert operation == "upload_part"
        assert ExpiresIn == 3600
        return f"https://s3.invalid/{Params['PartNumber']}"

    def complete_multipart_upload(self, **kwargs: object) -> None:
        self.completed = kwargs

    def head_object(self, **kwargs: object) -> dict[str, object]:
        return {"ContentLength": 96, "ContentType": "video/mp4"}

    def abort_multipart_upload(self, **kwargs: object) -> None:
        pass

    def get_object(self, **kwargs: object) -> dict[str, BytesIO]:
        return {"Body": BytesIO(self.objects[str(kwargs["Key"])])}

    def put_object(self, **kwargs: object) -> None:
        body = kwargs["Body"]
        self.objects[str(kwargs["Key"])] = body.read()
        self.put = kwargs


def test_s3_adapter_presigns_and_completes_multipart() -> None:
    client = FakeS3Client()
    store = S3ObjectStore(client, "vtv-local")
    upload = store.create_multipart(
        object_key="source/video.mp4", content_type="video/mp4", part_count=2
    )
    assert upload.provider_upload_id == "provider-123"
    assert [part.part_number for part in upload.parts] == [1, 2]
    assert store.uri_for("source/video.mp4") == "s3://vtv-local/source/video.mp4"

    stored = store.complete_multipart(
        object_key="source/video.mp4",
        provider_upload_id="provider-123",
        parts=[
            UploadPart(
                part_number=1, size_bytes=64, etag='"one"', checksum_sha256="YWJj"
            ),
            UploadPart(
                part_number=2, size_bytes=32, etag='"two"', checksum_sha256="ZGVm"
            ),
        ],
    )
    assert stored.size_bytes == 96
    assert client.completed
    assert client.completed["MultipartUpload"]["Parts"][1]["PartNumber"] == 2
    assert client.completed["MultipartUpload"]["Parts"][0]["ChecksumSHA256"] == "YWJj"


def test_s3_worker_transfer_verifies_download_and_uploads_immutable_output(
    tmp_path: Path,
) -> None:
    client = FakeS3Client()
    store = S3ObjectStore(client, "vtv-local")
    payload = client.objects["inputs/source.bin"]
    destination = tmp_path / "source.bin"

    store.download_file(
        object_uri="s3://vtv-local/inputs/source.bin",
        destination=destination,
        expected_sha256=sha256(payload).hexdigest(),
        expected_size_bytes=len(payload),
    )
    uploaded = store.upload_file(
        source=destination,
        object_key="outputs/result.bin",
        content_type="application/octet-stream",
    )

    assert destination.read_bytes() == payload
    assert uploaded.uri == "s3://vtv-local/outputs/result.bin"
    assert uploaded.sha256 == sha256(payload).hexdigest()
    assert client.put and client.put["Metadata"]["immutable"] == "true"


def test_s3_worker_download_removes_partial_file_on_integrity_failure(tmp_path: Path) -> None:
    store = S3ObjectStore(FakeS3Client(), "vtv-local")
    destination = tmp_path / "bad.bin"

    with pytest.raises(UploadIntegrityError, match="SHA-256"):
        store.download_file(
            object_uri="s3://vtv-local/inputs/source.bin",
            destination=destination,
            expected_sha256="0" * 64,
            expected_size_bytes=len(b"source bytes"),
        )

    assert not destination.exists()
    assert not list(tmp_path.glob("*.part"))


def test_s3_worker_upload_accepts_idempotent_existing_object(tmp_path: Path) -> None:
    payload = b"same output"

    class ExistingObjectClient(FakeS3Client):
        def put_object(self, **kwargs: object) -> None:
            raise ClientError(
                {"Error": {"Code": "PreconditionFailed", "Message": "exists"}},
                "PutObject",
            )

        def head_object(self, **kwargs: object) -> dict[str, object]:
            return {
                "ContentLength": len(payload),
                "Metadata": {"sha256": sha256(payload).hexdigest()},
            }

    source = tmp_path / "result.bin"
    source.write_bytes(payload)
    uploaded = S3ObjectStore(ExistingObjectClient(), "vtv-local").upload_file(
        source=source,
        object_key="outputs/existing.bin",
        content_type="application/octet-stream",
    )

    assert uploaded.sha256 == sha256(payload).hexdigest()
