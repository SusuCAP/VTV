from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, datetime
from hashlib import sha256
from pathlib import Path
from urllib.parse import unquote, urlparse

from vtv_delivery import C2paContentCredentials, C2paSignRequest
from vtv_schemas.jobs import AssetRef, DomainArtifact, StageJob, StageResult, VariantResult


@dataclass(frozen=True, slots=True)
class C2paWorker:
    """Passthrough C2PA signing worker.

    Does not invoke a real C2PA SDK. Generates a placeholder content-credentials
    JSON that records the delivery fingerprint and signer identity.
    """

    def execute(self, job: StageJob) -> StageResult:
        if job.stage_type != "C2PA_SIGN":
            raise ValueError(f"unsupported stage type: {job.stage_type}")
        return self._sign(job)

    def _sign(self, job: StageJob) -> StageResult:
        try:
            request = C2paSignRequest.model_validate(job.params["c2pa_sign_request"])
        except (KeyError, ValueError) as exc:
            raise ValueError("C2PA_SIGN requires a valid c2pa_sign_request in params") from exc

        output_directory = _local_path(job.output_prefix)
        output_directory.mkdir(parents=True, exist_ok=True)

        signed_at = datetime.now(UTC)
        credential_path = output_directory / "content-credentials.json"

        credentials = C2paContentCredentials(
            delivery_id=request.delivery_id,
            manifest_fingerprint=request.manifest_fingerprint,
            signer=request.signer_id,
            signed_at=signed_at,
            assertions=("c2pa.created",),
            credential_uri=credential_path.resolve().as_uri(),
        )

        payload = {
            "delivery_id": str(request.delivery_id),
            "manifest_fingerprint": request.manifest_fingerprint,
            "credentials": credentials.model_dump(mode="json"),
        }
        raw = json.dumps(
            payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")
        ).encode()
        _atomic_write(credential_path, raw)

        asset = _asset(credential_path, "application/json", {
            "delivery_id": str(request.delivery_id),
            "manifest_fingerprint": request.manifest_fingerprint,
            "signer_id": request.signer_id,
        })

        return StageResult(
            stage_run_id=job.stage_run_id,
            stage_attempt_id=job.stage_attempt_id,
            status="OUTPUT_READY",
            variants=[
                VariantResult(
                    variant_no=1,
                    output_assets=[asset],
                )
            ],
            domain_artifacts=[
                DomainArtifact(
                    document_type="C2PA_CREDENTIALS",
                    episode_id=job.episode_id,
                    source_asset_sha256=asset.sha256,
                    payload={
                        "delivery_id": str(request.delivery_id),
                        "manifest_fingerprint": request.manifest_fingerprint,
                        "signer_id": request.signer_id,
                        "signed_at": signed_at.isoformat(),
                        "credential_uri": asset.uri,
                        "credential_sha256": asset.sha256,
                        "credential_size_bytes": asset.size_bytes,
                    },
                )
            ],
            attempt_usage={"worker": "vtv-c2pa", "local": True},
        )


def _asset(path: Path, media_type: str, metadata: dict) -> AssetRef:
    return AssetRef(
        uri=path.resolve().as_uri(),
        sha256=_sha256(path),
        media_type=media_type,
        size_bytes=path.stat().st_size,
        metadata=metadata,
    )


def _sha256(path: Path) -> str:
    digest = sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(4 * 1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def _local_path(uri: str) -> Path:
    parsed = urlparse(uri)
    if parsed.scheme not in {"", "file"}:
        raise ValueError("c2pa worker requires local file URIs")
    return Path(unquote(parsed.path if parsed.scheme else uri))


def _atomic_write(path: Path, content: bytes) -> None:
    tmp = path.with_suffix(path.suffix + ".tmp")
    try:
        tmp.write_bytes(content)
        tmp.replace(path)
    finally:
        tmp.unlink(missing_ok=True)
