from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from hashlib import sha256
from pathlib import Path
from typing import Protocol
from urllib.parse import unquote, urlparse

from vtv_delivery import C2paContentCredentials, C2paSignRequest
from vtv_schemas.jobs import AssetRef, DomainArtifact, StageJob, StageResult, VariantResult


@dataclass(frozen=True, slots=True)
class C2paSignerOutput:
    credential_path: Path
    signed_master_path: Path | None
    assertions: tuple[str, ...]
    signed_at: datetime


class C2paSigner(Protocol):
    @property
    def signer_id(self) -> str: ...

    def sign(
        self,
        request: C2paSignRequest,
        master_path: Path,
        output_directory: Path,
    ) -> C2paSignerOutput: ...


@dataclass(frozen=True, slots=True)
class C2paWorker:
    """C2PA signing boundary.

    The repository does not vendor a C2PA implementation. Refusing execution
    is safer than emitting JSON that falsely claims to be a signed credential.
    A deployment must inject a real SDK-backed worker before enabling this stage.
    """

    signer: C2paSigner | None = None

    def execute(self, job: StageJob) -> StageResult:
        if job.stage_type != "C2PA_SIGN":
            raise ValueError(f"unsupported stage type: {job.stage_type}")
        try:
            request = C2paSignRequest.model_validate(job.params["c2pa_sign_request"])
        except (KeyError, ValueError) as exc:
            raise ValueError("C2PA_SIGN requires a valid c2pa_sign_request in params") from exc
        if self.signer is None:
            raise RuntimeError(
                "C2PA_SIGN is unavailable: inject a real C2PA SDK-backed signer"
            )
        if self.signer.signer_id != request.signer_id:
            raise ValueError("C2PA signer identity does not match the immutable request")
        master_sha256 = job.params.get("master_sha256")
        if not isinstance(master_sha256, str):
            raise ValueError("C2PA_SIGN requires master_sha256")
        master_assets = [
            asset for asset in job.input_assets if asset.sha256 == master_sha256
        ]
        if len(master_assets) != 1:
            raise ValueError("C2PA_SIGN requires exactly one matching master input")
        master_path = _local_path(master_assets[0].uri)
        if _sha256(master_path) != master_sha256:
            raise ValueError("C2PA master input SHA-256 mismatch")

        output_directory = _local_path(job.output_prefix)
        output_directory.mkdir(parents=True, exist_ok=True)
        signed = self.signer.sign(request, master_path, output_directory)
        if not signed.credential_path.is_file():
            raise RuntimeError("C2PA signer did not produce a credential artifact")
        credential_asset = _asset(
            signed.credential_path,
            "application/c2pa",
            {
                "delivery_id": str(request.delivery_id),
                "manifest_fingerprint": request.manifest_fingerprint,
                "signer_id": request.signer_id,
            },
        )
        credentials = C2paContentCredentials(
            delivery_id=request.delivery_id,
            manifest_fingerprint=request.manifest_fingerprint,
            signer=request.signer_id,
            signed_at=signed.signed_at,
            assertions=signed.assertions,
            credential_uri=credential_asset.uri,
        )
        output_assets = [credential_asset]
        if signed.signed_master_path is not None:
            if not signed.signed_master_path.is_file():
                raise RuntimeError("C2PA signer reported a missing signed master")
            output_assets.append(
                _asset(
                    signed.signed_master_path,
                    master_assets[0].media_type,
                    {
                        "delivery_id": str(request.delivery_id),
                        "role": "C2PA_SIGNED_MASTER",
                    },
                )
            )

        return StageResult(
            stage_run_id=job.stage_run_id,
            stage_attempt_id=job.stage_attempt_id,
            status="OUTPUT_READY",
            variants=[
                VariantResult(
                    variant_no=1,
                    output_assets=output_assets,
                )
            ],
            domain_artifacts=[
                DomainArtifact(
                    document_type="C2PA_CREDENTIALS",
                    episode_id=job.episode_id,
                    source_asset_sha256=credential_asset.sha256,
                    payload={
                        "delivery_id": str(request.delivery_id),
                        "manifest_fingerprint": request.manifest_fingerprint,
                        "signer_id": request.signer_id,
                        "signed_at": signed.signed_at.isoformat(),
                        "assertions": list(signed.assertions),
                        "credential_uri": credential_asset.uri,
                        "credential_sha256": credential_asset.sha256,
                        "credential_size_bytes": credential_asset.size_bytes,
                        "credentials": credentials.model_dump(mode="json"),
                        "signed_master_sha256": (
                            output_assets[1].sha256 if len(output_assets) == 2 else None
                        ),
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
