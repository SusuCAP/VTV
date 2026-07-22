from vtv_schemas.uploads import UploadPart
from vtv_storage.s3 import S3ObjectStore


class FakeS3Client:
    def __init__(self) -> None:
        self.completed: dict | None = None

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
