from uuid import uuid4

from vtv_schemas.uploads import PresignedPart, UploadPart

from .adapter import BackendMultipart, StoredObject, UploadNotFoundError


class MemoryObjectStore:
    """Deterministic object-store backend used by local API and contract tests."""

    def __init__(self) -> None:
        self._uploads: dict[str, tuple[str, str]] = {}

    def uri_for(self, object_key: str) -> str:
        return f"memory://{object_key}"

    def create_multipart(
        self,
        *,
        object_key: str,
        content_type: str,
        part_count: int,
    ) -> BackendMultipart:
        provider_upload_id = str(uuid4())
        self._uploads[provider_upload_id] = (object_key, content_type)
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
        state = self._uploads.get(provider_upload_id)
        if state is None or state[0] != object_key:
            raise UploadNotFoundError(provider_upload_id)
        return [
            PresignedPart(
                part_number=number,
                url=f"https://object-store.invalid/{provider_upload_id}/parts/{number}",
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
        state = self._uploads.get(provider_upload_id)
        if state is None or state[0] != object_key:
            raise UploadNotFoundError(provider_upload_id)
        del self._uploads[provider_upload_id]
        return StoredObject(
            size_bytes=sum(part.size_bytes for part in parts),
            content_type=state[1],
            checksum_sha256=None,
        )

    def abort_multipart(self, *, object_key: str, provider_upload_id: str) -> None:
        state = self._uploads.get(provider_upload_id)
        if state is None or state[0] != object_key:
            raise UploadNotFoundError(provider_upload_id)
        del self._uploads[provider_upload_id]
