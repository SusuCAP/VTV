import json
from hashlib import sha256
from pathlib import Path
from urllib.parse import unquote, urlparse

from vtv_media import detect_shots, generate_proxy, probe_media
from vtv_schemas.jobs import AssetRef, StageJob, StageResult, VariantResult

SUPPORTED_STAGES = {"INGEST_VALIDATE", "PROXY_GENERATE", "SHOT_DETECT"}


def _local_path(uri: str) -> Path:
    parsed = urlparse(uri)
    if parsed.scheme not in {"", "file"}:
        raise ValueError(f"media worker local mode cannot resolve URI scheme: {parsed.scheme}")
    return Path(unquote(parsed.path if parsed.scheme else uri))


def _output_directory(prefix: str) -> Path:
    directory = _local_path(prefix)
    directory.mkdir(parents=True, exist_ok=True)
    return directory


def _asset(path: Path, media_type: str) -> AssetRef:
    digest = sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(4 * 1024 * 1024):
            digest.update(chunk)
    return AssetRef(
        uri=path.resolve().as_uri(),
        sha256=digest.hexdigest(),
        media_type=media_type,
        size_bytes=path.stat().st_size,
    )


def execute(job: StageJob) -> StageResult:
    if job.stage_type not in SUPPORTED_STAGES:
        raise ValueError(f"unsupported media stage: {job.stage_type}")
    if not job.input_assets:
        raise ValueError("media stage requires at least one input asset")
    source = _local_path(job.input_assets[0].uri)
    output_directory = _output_directory(job.output_prefix)
    if job.stage_type == "INGEST_VALIDATE":
        output = output_directory / "probe.json"
        output.write_text(
            json.dumps(probe_media(source).model_dump(mode="json"), ensure_ascii=False, indent=2)
        )
        media_type = "application/json"
    elif job.stage_type == "PROXY_GENERATE":
        output = generate_proxy(source, output_directory / "proxy.mp4")
        media_type = "video/mp4"
    else:
        output = output_directory / "shots.json"
        shots = [shot.model_dump(mode="json") for shot in detect_shots(source)]
        output.write_text(json.dumps({"shots": shots}, ensure_ascii=False, indent=2))
        media_type = "application/json"
    return StageResult(
        stage_run_id=job.stage_run_id,
        stage_attempt_id=job.stage_attempt_id,
        status="OUTPUT_READY",
        variants=[
            VariantResult(
                variant_no=1,
                output_assets=[_asset(output, media_type)],
                raw_metrics={"worker": "media", "stage_type": job.stage_type},
            )
        ],
        attempt_usage={"worker": "media", "local": True},
    )
