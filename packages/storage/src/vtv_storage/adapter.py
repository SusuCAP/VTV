from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from vtv_schemas.jobs import AssetRef
from vtv_schemas.uploads import PresignedPart, UploadPart


class UploadIntegrityError(ValueError):
    pass


class UploadNotFoundError(KeyError):
    pass


@dataclass(frozen=True, slots=True)
class BackendMultipart:
    provider_upload_id: str
    parts: list[PresignedPart]


@dataclass(frozen=True, slots=True)
class StoredObject:
    size_bytes: int
    content_type: str
    checksum_sha256: str | None


class ObjectStoreAdapter(Protocol):
    def uri_for(self, object_key: str) -> str: ...

    def presign_download(self, *, object_uri: str) -> str: ...

    def create_multipart(
        self,
        *,
        object_key: str,
        content_type: str,
        part_count: int,
    ) -> BackendMultipart: ...

    def presign_parts(
        self,
        *,
        object_key: str,
        provider_upload_id: str,
        part_numbers: list[int],
    ) -> list[PresignedPart]: ...

    def complete_multipart(
        self,
        *,
        object_key: str,
        provider_upload_id: str,
        parts: list[UploadPart],
    ) -> StoredObject: ...

    def abort_multipart(self, *, object_key: str, provider_upload_id: str) -> None: ...


class WorkerObjectStoreAdapter(Protocol):
    def download_file(
        self,
        *,
        object_uri: str,
        destination: Path,
        expected_sha256: str,
        expected_size_bytes: int,
    ) -> Path: ...

    def upload_file(
        self, *, source: Path, object_key: str, content_type: str
    ) -> AssetRef: ...
