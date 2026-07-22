from dataclasses import dataclass, field
from math import ceil
from uuid import UUID, uuid4

from vtv_schemas.uploads import (
    MultipartComplete,
    MultipartInit,
    MultipartUpload,
    PresignedPart,
    UploadRead,
)

from .adapter import UploadIntegrityError, UploadNotFoundError


@dataclass(slots=True)
class _UploadState:
    workspace_id: UUID
    request: MultipartInit
    object_key: str
    status: str = "UPLOADING"
    completed_parts: list = field(default_factory=list)


class MemoryObjectStore:
    """Contract test adapter. It issues opaque URLs and never receives media bytes."""

    def __init__(self) -> None:
        self._uploads: dict[UUID, _UploadState] = {}

    def multipart_init(self, workspace_id: UUID, request: MultipartInit) -> MultipartUpload:
        upload_id = uuid4()
        safe_name = request.filename.replace("/", "_").replace("\\", "_")
        object_key = (
            f"workspaces/{workspace_id}/projects/{request.project_id}"
            f"/source/{upload_id}/{safe_name}"
        )
        part_count = ceil(request.size_bytes / request.part_size_bytes)
        parts = [
            PresignedPart(
                part_number=number,
                url=f"https://object-store.invalid/multipart/{upload_id}/parts/{number}",
            )
            for number in range(1, part_count + 1)
        ]
        self._uploads[upload_id] = _UploadState(workspace_id, request, object_key)
        return MultipartUpload(
            upload_id=upload_id,
            object_key=object_key,
            part_size_bytes=request.part_size_bytes,
            parts=parts,
        )

    def multipart_complete(
        self, workspace_id: UUID, upload_id: UUID, request: MultipartComplete
    ) -> UploadRead:
        state = self._state(workspace_id, upload_id)
        part_numbers = [part.part_number for part in request.parts]
        if part_numbers != list(range(1, len(request.parts) + 1)):
            raise UploadIntegrityError("parts must be complete, unique, and ordered from 1")
        if sum(part.size_bytes for part in request.parts) != state.request.size_bytes:
            raise UploadIntegrityError("completed part sizes do not match declared object size")
        if (
            state.request.sha256
            and request.object_checksum_sha256
            and state.request.sha256 != request.object_checksum_sha256
        ):
            raise UploadIntegrityError("object SHA-256 does not match upload declaration")
        state.completed_parts = list(request.parts)
        state.status = "COMPLETED"
        return self.get_upload(workspace_id, upload_id)

    def get_upload(self, workspace_id: UUID, upload_id: UUID) -> UploadRead:
        state = self._state(workspace_id, upload_id)
        return UploadRead(
            upload_id=upload_id,
            project_id=state.request.project_id,
            object_key=state.object_key,
            size_bytes=state.request.size_bytes,
            status=state.status,
            completed_parts=state.completed_parts,
        )

    def _state(self, workspace_id: UUID, upload_id: UUID) -> _UploadState:
        state = self._uploads.get(upload_id)
        if state is None or state.workspace_id != workspace_id:
            raise UploadNotFoundError(upload_id)
        return state
