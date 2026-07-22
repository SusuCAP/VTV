from uuid import UUID

from pydantic import BaseModel, Field

MIN_PART_SIZE = 32 * 1024 * 1024
MAX_PART_SIZE = 128 * 1024 * 1024


class MultipartInit(BaseModel):
    project_id: UUID
    filename: str = Field(min_length=1, max_length=255)
    content_type: str = Field(min_length=1, max_length=200)
    size_bytes: int = Field(gt=0)
    part_size_bytes: int = Field(default=64 * 1024 * 1024, ge=MIN_PART_SIZE, le=MAX_PART_SIZE)
    sha256: str | None = Field(default=None, pattern=r"^[a-f0-9]{64}$")


class UploadPart(BaseModel):
    part_number: int = Field(ge=1, le=10_000)
    size_bytes: int = Field(gt=0)
    etag: str = Field(min_length=1, max_length=512)
    checksum_sha256: str | None = Field(default=None, pattern=r"^[A-Za-z0-9+/=_-]+$")


class PresignedPart(BaseModel):
    part_number: int
    url: str


class MultipartUpload(BaseModel):
    upload_id: UUID
    object_key: str
    part_size_bytes: int
    parts: list[PresignedPart]


class MultipartComplete(BaseModel):
    parts: list[UploadPart] = Field(min_length=1)
    object_checksum_sha256: str | None = Field(default=None, pattern=r"^[a-f0-9]{64}$")


class UploadRead(BaseModel):
    upload_id: UUID
    project_id: UUID
    object_key: str
    size_bytes: int
    status: str
    completed_parts: list[UploadPart] = Field(default_factory=list)
