import json
from hashlib import sha256
from pathlib import Path
from urllib.parse import unquote, urlparse

from vtv_media import detect_shots, generate_proxy, probe_media
from vtv_schemas.jobs import AssetRef, DomainArtifact, StageJob, StageResult, VariantResult

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


def _asset(path: Path, media_type: str, metadata: dict | None = None) -> AssetRef:
    digest = sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(4 * 1024 * 1024):
            digest.update(chunk)
    return AssetRef(
        uri=path.resolve().as_uri(),
        sha256=digest.hexdigest(),
        media_type=media_type,
        size_bytes=path.stat().st_size,
        metadata=metadata or {},
    )


def execute(job: StageJob) -> StageResult:
    if job.stage_type not in SUPPORTED_STAGES:
        raise ValueError(f"unsupported media stage: {job.stage_type}")
    if not job.input_assets:
        raise ValueError("media stage requires at least one input asset")
    source = _local_path(job.input_assets[0].uri)
    output_directory = _output_directory(job.output_prefix)
    if job.stage_type == "INGEST_VALIDATE":
        domain_payload = probe_media(source).model_dump(mode="json")
        output = output_directory / "probe.json"
        output.write_text(
            json.dumps(domain_payload, ensure_ascii=False, indent=2)
        )
        media_type = "application/json"
        document_type = "MEDIA_PROBE"
    elif job.stage_type == "PROXY_GENERATE":
        output = generate_proxy(source, output_directory / "proxy.mp4")
        media_type = "video/mp4"
        proxy = probe_media(output)
        video = proxy.video_streams[0]
        asset_metadata = {
            "duration_seconds": proxy.duration_seconds,
            "width": video.width,
            "height": video.height,
            "fps": video.frame_rate,
        }
        domain_payload = None
        document_type = None
    else:
        output = output_directory / "shots.json"
        shots = [shot.model_dump(mode="json") for shot in detect_shots(source)]
        domain_payload = {"shots": shots}
        output.write_text(json.dumps(domain_payload, ensure_ascii=False, indent=2))
        media_type = "application/json"
        document_type = "SHOT_LIST"
        asset_metadata = {}
    if job.stage_type == "INGEST_VALIDATE":
        asset_metadata = {}
    asset = _asset(output, media_type, asset_metadata)
    return StageResult(
        stage_run_id=job.stage_run_id,
        stage_attempt_id=job.stage_attempt_id,
        status="OUTPUT_READY",
        variants=[
            VariantResult(
                variant_no=1,
                output_assets=[asset],
                raw_metrics={"worker": "media", "stage_type": job.stage_type},
            )
        ],
        domain_artifacts=(
            [
                DomainArtifact(
                    document_type=document_type,
                    episode_id=job.episode_id,
                    source_asset_sha256=asset.sha256,
                    payload=domain_payload,
                )
            ]
            if document_type and domain_payload is not None
            else []
        ),
        attempt_usage={"worker": "media", "local": True},
    )
