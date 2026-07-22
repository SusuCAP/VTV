import boto3
from vtv_storage import MemoryObjectStore, ObjectStoreAdapter, S3ObjectStore

from .config import Settings


def create_object_store(settings: Settings) -> ObjectStoreAdapter:
    if not settings.s3_endpoint:
        return MemoryObjectStore()
    if not settings.s3_access_key or not settings.s3_secret_key:
        raise ValueError("S3 access key and secret key are required when VTV_S3_ENDPOINT is set")
    client = boto3.client(
        "s3",
        endpoint_url=settings.s3_endpoint,
        region_name=settings.s3_region,
        aws_access_key_id=settings.s3_access_key,
        aws_secret_access_key=settings.s3_secret_key,
    )
    return S3ObjectStore(client, settings.s3_bucket)
