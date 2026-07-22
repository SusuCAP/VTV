import pytest
from pydantic import ValidationError
from vtv_schemas.jobs import DomainArtifact


def test_domain_artifact_requires_versioned_uppercase_type_and_asset_digest() -> None:
    artifact = DomainArtifact(
        document_type="SHOT_LIST",
        schema_version=2,
        source_asset_sha256="a" * 64,
        payload={"shots": []},
    )
    assert artifact.schema_version == 2

    with pytest.raises(ValidationError):
        DomainArtifact(
            document_type="shot-list",
            source_asset_sha256="invalid",
            payload={},
        )
