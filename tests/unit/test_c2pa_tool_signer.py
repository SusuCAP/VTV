import json
import subprocess
from pathlib import Path
from uuid import uuid4

import pytest
from vtv_c2pa import C2paToolSigner, C2paWorker
from vtv_delivery import C2paSignRequest


class FakeC2paTool:
    def __init__(self, fingerprint: str, signer_id: str) -> None:
        self.fingerprint = fingerprint
        self.signer_id = signer_id
        self.calls: list[tuple[list[str], dict[str, str]]] = []

    def __call__(
        self,
        command,
        *,
        timeout_seconds: float,
        environment,
    ) -> subprocess.CompletedProcess[str]:
        assert timeout_seconds == 60
        self.calls.append((list(command), dict(environment)))
        if "--manifest" in command:
            source = Path(command[1])
            manifest_path = Path(command[command.index("--manifest") + 1])
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            assert "private_key" not in manifest
            assert "sign_cert" not in manifest
            assert manifest["assertions"][1]["data"]["manifest_fingerprint"] == (
                self.fingerprint
            )
            output = Path(command[command.index("--output") + 1])
            output.write_bytes(source.read_bytes() + b"-c2pa")
            return subprocess.CompletedProcess(command, 0, "{}", "")
        report = {
            "active_manifest": "urn:uuid:manifest",
            "manifests": {
                "urn:uuid:manifest": {
                    "assertions": [
                        {
                            "label": "org.vtv.delivery.v1",
                            "data": {
                                "manifest_fingerprint": self.fingerprint,
                                "signer_id": self.signer_id,
                            },
                        }
                    ]
                }
            },
            "validation_status": [],
        }
        return subprocess.CompletedProcess(command, 0, json.dumps(report), "")


def _request(fingerprint: str, signer_id: str) -> C2paSignRequest:
    return C2paSignRequest(
        delivery_id=uuid4(),
        manifest_fingerprint=fingerprint,
        master_object_uri="s3://bucket/master.mp4",
        output_prefix="s3://bucket/c2pa",
        signer_id=signer_id,
    )


def test_c2patool_signer_embeds_then_verifies_without_key_environment(
    monkeypatch,
    tmp_path: Path,
) -> None:
    fingerprint = "b" * 64
    signer_id = "kms:delivery-signing"
    runner = FakeC2paTool(fingerprint, signer_id)
    master = tmp_path / "master.mp4"
    master.write_bytes(b"master")
    tool = tmp_path / "c2patool"
    signer = tmp_path / "kms-signer"
    tool.write_bytes(b"tool")
    signer.write_bytes(b"signer")
    monkeypatch.setenv("C2PA_PRIVATE_KEY", "must-not-propagate")
    monkeypatch.setenv("C2PA_SIGN_CERT", "must-not-propagate")

    output = C2paToolSigner(
        signer_id=signer_id,
        tool_path=tool,
        signer_path=signer,
        timeout_seconds=60,
        runner=runner,
    ).sign(_request(fingerprint, signer_id), master, tmp_path / "output")

    assert output.signed_master_path is not None
    assert output.signed_master_path.read_bytes() == b"master-c2pa"
    assert output.credential_path.is_file()
    assert "--signer-path" in runner.calls[0][0]
    assert "C2PA_PRIVATE_KEY" not in runner.calls[0][1]
    assert "C2PA_SIGN_CERT" not in runner.calls[0][1]


def test_c2patool_signer_rejects_failed_verification(tmp_path: Path) -> None:
    fingerprint = "c" * 64
    signer_id = "kms:delivery-signing"
    runner = FakeC2paTool(fingerprint, signer_id)
    master = tmp_path / "master.mp4"
    master.write_bytes(b"master")

    def invalid_report(command, *, timeout_seconds, environment):
        result = runner(
            command,
            timeout_seconds=timeout_seconds,
            environment=environment,
        )
        if "--manifest" not in command:
            report = json.loads(result.stdout)
            report["validation_status"] = [{"code": "claimSignature.mismatch"}]
            result = subprocess.CompletedProcess(
                command,
                0,
                json.dumps(report),
                "",
            )
        return result

    signer = C2paToolSigner(
        signer_id=signer_id,
        tool_path=tmp_path / "c2patool",
        signer_path=tmp_path / "kms-signer",
        timeout_seconds=60,
        runner=invalid_report,
    )

    with pytest.raises(RuntimeError, match="claimSignature.mismatch"):
        signer.sign(_request(fingerprint, signer_id), master, tmp_path / "output")


def test_environment_factory_requires_external_executables(
    tmp_path: Path,
) -> None:
    tool = tmp_path / "c2patool"
    signer = tmp_path / "kms-signer"
    tool.write_bytes(b"tool")
    signer.write_bytes(b"signer")
    tool.chmod(0o700)
    signer.chmod(0o700)
    environment = {
        "VTV_C2PA_SIGNER_ID": "kms:delivery-signing",
        "VTV_C2PA_TOOL_PATH": str(tool),
        "VTV_C2PA_SIGNER_PATH": str(signer),
        "VTV_C2PA_TIMEOUT_SECONDS": "60",
    }

    worker = C2paWorker.from_environment(environment)

    assert isinstance(worker.signer, C2paToolSigner)
    assert worker.signer.tool_path == tool.resolve()
    assert worker.signer.signer_path == signer.resolve()
