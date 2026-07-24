from __future__ import annotations

import json
import os
import shutil
import subprocess
import tempfile
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from hashlib import sha256
from pathlib import Path
from typing import Protocol
from urllib.parse import unquote, urlparse

from vtv_delivery import C2paContentCredentials, C2paSignRequest
from vtv_schemas.jobs import AssetRef, DomainArtifact, StageJob, StageResult, VariantResult


@dataclass(frozen=True, slots=True)
class C2paSignerOutput:
    credential_path: Path
    signed_master_path: Path
    assertions: tuple[str, ...]
    signed_at: datetime
    credential_media_type: str = "application/json"
    verification_statuses: tuple[str, ...] = ()


class C2paSigner(Protocol):
    @property
    def signer_id(self) -> str: ...

    def sign(
        self,
        request: C2paSignRequest,
        master_path: Path,
        output_directory: Path,
    ) -> C2paSignerOutput: ...


class C2paCommandRunner(Protocol):
    def __call__(
        self,
        command: Sequence[str],
        *,
        timeout_seconds: float,
        environment: Mapping[str, str],
    ) -> subprocess.CompletedProcess[str]: ...


def _run_command(
    command: Sequence[str],
    *,
    timeout_seconds: float,
    environment: Mapping[str, str],
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        list(command),
        check=True,
        capture_output=True,
        text=True,
        timeout=timeout_seconds,
        env=dict(environment),
    )


@dataclass(frozen=True, slots=True)
class C2paToolSigner:
    """Production c2patool adapter using an external KMS/HSM signer process."""

    signer_id: str
    tool_path: Path
    signer_path: Path
    timeout_seconds: float = 300
    settings_path: Path | None = None
    runner: C2paCommandRunner = _run_command

    def sign(
        self,
        request: C2paSignRequest,
        master_path: Path,
        output_directory: Path,
    ) -> C2paSignerOutput:
        output_directory.mkdir(parents=True, exist_ok=True)
        signed_master = output_directory / (
            f"{master_path.stem}.content-credentials{master_path.suffix}"
        )
        credential_report = output_directory / "content-credentials.json"
        manifest = _manifest_definition(request, master_path)
        environment = dict(os.environ)
        environment.pop("C2PA_PRIVATE_KEY", None)
        environment.pop("C2PA_SIGN_CERT", None)

        with tempfile.TemporaryDirectory(
            prefix="vtv-c2pa-",
            dir=output_directory,
        ) as temporary:
            manifest_path = Path(temporary) / "manifest.json"
            manifest_path.write_text(
                json.dumps(manifest, ensure_ascii=False, sort_keys=True),
                encoding="utf-8",
            )
            command = [
                str(self.tool_path),
                str(master_path),
                "--manifest",
                str(manifest_path),
                "--output",
                str(signed_master),
                "--signer-path",
                str(self.signer_path),
                "--force",
            ]
            if self.settings_path is not None:
                command.extend(("--settings", str(self.settings_path)))
            self.runner(
                command,
                timeout_seconds=self.timeout_seconds,
                environment=environment,
            )

        if not signed_master.is_file() or signed_master.stat().st_size == 0:
            raise RuntimeError("c2patool did not produce a non-empty signed master")
        verification_command = [str(self.tool_path), str(signed_master)]
        if self.settings_path is not None:
            verification_command.extend(("--settings", str(self.settings_path)))
        verification = self.runner(
            verification_command,
            timeout_seconds=self.timeout_seconds,
            environment=environment,
        )
        try:
            report = json.loads(verification.stdout)
        except json.JSONDecodeError as exc:
            raise RuntimeError("c2patool verification did not return valid JSON") from exc
        if not isinstance(report, dict):
            raise RuntimeError("c2patool verification report must be a JSON object")
        if not _contains_json_value(report, request.manifest_fingerprint):
            raise RuntimeError("signed C2PA manifest is missing the delivery fingerprint")
        if not _contains_json_value(report, request.signer_id):
            raise RuntimeError("signed C2PA manifest is missing the configured signer identity")
        statuses = _verification_statuses(report)
        if statuses:
            raise RuntimeError(
                "c2patool verification reported failures: " + ", ".join(statuses)
            )
        credential_report.write_text(
            json.dumps(
                {
                    "schema_version": "vtv.c2pa-verification.v1",
                    "delivery_id": str(request.delivery_id),
                    "manifest_fingerprint": request.manifest_fingerprint,
                    "signer_id": request.signer_id,
                    "signed_master_sha256": _sha256(signed_master),
                    "verification": report,
                },
                ensure_ascii=False,
                sort_keys=True,
            ),
            encoding="utf-8",
        )
        return C2paSignerOutput(
            credential_path=credential_report,
            signed_master_path=signed_master,
            assertions=("c2pa.actions.v2", "org.vtv.delivery.v1"),
            signed_at=datetime.now(UTC),
            verification_statuses=statuses,
        )


@dataclass(frozen=True, slots=True)
class C2paWorker:
    """C2PA signing boundary.

    Production construction uses :meth:`from_environment` to bind c2patool to
    an external KMS/HSM signer. Direct construction remains available for
    dependency-injected signers and refuses to run when no signer is supplied.
    """

    signer: C2paSigner | None = None

    @classmethod
    def from_environment(
        cls,
        environment: Mapping[str, str] | None = None,
        *,
        runner: C2paCommandRunner = _run_command,
    ) -> C2paWorker:
        values = os.environ if environment is None else environment
        signer_id = values.get("VTV_C2PA_SIGNER_ID", "").strip()
        if not signer_id:
            raise RuntimeError("VTV_C2PA_SIGNER_ID is required for C2PA signing")
        tool_path = _resolve_executable(
            values.get("VTV_C2PA_TOOL_PATH", "c2patool"),
            "VTV_C2PA_TOOL_PATH",
        )
        signer_path = _resolve_executable(
            values.get("VTV_C2PA_SIGNER_PATH", ""),
            "VTV_C2PA_SIGNER_PATH",
        )
        timeout_seconds = float(values.get("VTV_C2PA_TIMEOUT_SECONDS", "300"))
        if not 10 <= timeout_seconds <= 3600:
            raise ValueError("VTV_C2PA_TIMEOUT_SECONDS must be within [10, 3600]")
        settings_value = values.get("VTV_C2PA_SETTINGS_PATH", "").strip()
        settings_path = Path(settings_value).resolve() if settings_value else None
        if settings_path is not None and not settings_path.is_file():
            raise RuntimeError("VTV_C2PA_SETTINGS_PATH must point to a readable file")
        return cls(
            signer=C2paToolSigner(
                signer_id=signer_id,
                tool_path=tool_path,
                signer_path=signer_path,
                timeout_seconds=timeout_seconds,
                settings_path=settings_path,
                runner=runner,
            )
        )

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
        if signed.signed_at.tzinfo is None:
            raise RuntimeError("C2PA signer returned a timezone-naive signing time")
        credential_asset = _asset(
            signed.credential_path,
            signed.credential_media_type,
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
                        "verification_statuses": list(signed.verification_statuses),
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


def _resolve_executable(value: str, setting_name: str) -> Path:
    candidate = value.strip()
    if not candidate:
        raise RuntimeError(f"{setting_name} is required for C2PA signing")
    resolved = shutil.which(candidate)
    if resolved is None:
        raise RuntimeError(f"{setting_name} does not resolve to an executable")
    path = Path(resolved).resolve()
    if not path.is_file() or not os.access(path, os.X_OK):
        raise RuntimeError(f"{setting_name} must point to an executable file")
    return path


def _manifest_definition(
    request: C2paSignRequest,
    master_path: Path,
) -> dict[str, object]:
    return {
        "claim_generator_info": [{"name": "VTV", "version": "0.1.0"}],
        "title": master_path.name,
        "assertions": [
            {
                "label": "c2pa.actions.v2",
                "data": {
                    "actions": [
                        {
                            "action": "c2pa.edited",
                            "softwareAgent": "VTV/0.1.0",
                        }
                    ],
                    "allActionsIncluded": True,
                },
            },
            {
                "label": "org.vtv.delivery.v1",
                "data": {
                    "delivery_id": str(request.delivery_id),
                    "manifest_fingerprint": request.manifest_fingerprint,
                    "signer_id": request.signer_id,
                    "master_sha256": _sha256(master_path),
                },
            },
        ],
    }


def _contains_json_value(value: object, expected: str) -> bool:
    if value == expected:
        return True
    if isinstance(value, dict):
        return any(_contains_json_value(item, expected) for item in value.values())
    if isinstance(value, list):
        return any(_contains_json_value(item, expected) for item in value)
    return False


def _verification_statuses(report: Mapping[str, object]) -> tuple[str, ...]:
    raw = report.get("validation_status")
    if raw is None:
        active_label = report.get("active_manifest")
        manifests = report.get("manifests")
        if not isinstance(active_label, str) or not isinstance(manifests, dict):
            return ("manifest.missing",)
        return ()
    if not isinstance(raw, list):
        return ("validation_status.invalid",)
    statuses: list[str] = []
    for item in raw:
        if isinstance(item, dict):
            code = item.get("code")
            statuses.append(str(code or "validation.unknown"))
        else:
            statuses.append("validation.unknown")
    return tuple(statuses)
