from typing import Protocol
from uuid import UUID

from vtv_schemas.uploads import MultipartComplete, MultipartInit, MultipartUpload, UploadRead


class UploadIntegrityError(ValueError):
    pass


class UploadNotFoundError(KeyError):
    pass


class ObjectStoreAdapter(Protocol):
    def multipart_init(self, workspace_id: UUID, request: MultipartInit) -> MultipartUpload: ...

    def multipart_complete(
        self, workspace_id: UUID, upload_id: UUID, request: MultipartComplete
    ) -> UploadRead: ...

    def get_upload(self, workspace_id: UUID, upload_id: UUID) -> UploadRead: ...
