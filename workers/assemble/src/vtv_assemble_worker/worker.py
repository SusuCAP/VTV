from __future__ import annotations

import json
from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path
from urllib.parse import unquote, urlparse
from uuid import UUID, uuid4

from PIL import Image, ImageDraw, ImageFont
from vtv_assembly import (
    AudioMixRequest,
    EpisodeAssemblyRequest,
    MixRole,
    PictureConformRequest,
    SubtitleDocument,
    render_srt,
    render_vtt,
)
from vtv_delivery import DeliveryEvidenceRequest, QcEvidence
from vtv_media import probe_media
from vtv_media.process import run_media_process
from vtv_routing import (
    EpisodeWorkflowPlan,
    ShotVisualFeatures,
    VisualShotRouter,
)
from vtv_schemas.jobs import AssetRef, DomainArtifact, StageJob, StageResult, VariantResult


@dataclass(frozen=True, slots=True)
class AssembleWorker:
    ffmpeg_executable: str = "ffmpeg"
    timeout_seconds: int = 1800

    def execute(self, job: StageJob) -> StageResult:
        if job.stage_type == "SUBTITLE_RENDER":
            return self._subtitle(job)
        if job.stage_type == "AUDIO_MIX":
            return self._audio_mix(job)
        if job.stage_type == "ASSEMBLE_EPISODE":
            return self._assemble(job)
        if job.stage_type == "PICTURE_CONFORM":
            return self._picture_conform(job)
        if job.stage_type == "DELIVERY_EVIDENCE":
            return self._delivery_evidence(job)
        if job.stage_type == "SHOT_ROUTING":
            return self._shot_routing(job)
        raise ValueError(f"unsupported assemble stage: {job.stage_type}")

    def _subtitle(self, job: StageJob) -> StageResult:
        if job.input_assets:
            raise ValueError("SUBTITLE_RENDER consumes its immutable document from params")
        try:
            document = SubtitleDocument.model_validate(job.params["subtitle_document"])
        except (KeyError, ValueError) as exc:
            raise ValueError("SUBTITLE_RENDER requires a valid subtitle_document") from exc
        formats = tuple(job.params.get("formats", ("srt",)))
        if not formats or any(item not in {"srt", "vtt"} for item in formats):
            raise ValueError("subtitle formats must contain srt and/or vtt")
        if len(formats) != len(set(formats)):
            raise ValueError("subtitle formats must be unique")
        output_directory = _local_path(job.output_prefix)
        output_directory.mkdir(parents=True, exist_ok=True)
        assets: list[AssetRef] = []
        for format_name in formats:
            path = output_directory / f"subtitles.{format_name}"
            content = render_srt(document) if format_name == "srt" else render_vtt(document)
            _atomic_write(path, content.encode())
            media_type = "application/x-subrip" if format_name == "srt" else "text/vtt"
            assets.append(_asset(path, media_type, {"locale": document.locale}))
        return _result(
            job,
            assets,
            "SUBTITLE_DOCUMENT",
            {
                "locale": document.locale,
                "cue_count": len(document.cues),
                "formats": formats,
            },
            sha256(document.model_dump_json().encode()).hexdigest(),
        )

    def _audio_mix(self, job: StageJob) -> StageResult:
        try:
            request = AudioMixRequest.model_validate(job.params["audio_mix_request"])
        except (KeyError, ValueError) as exc:
            raise ValueError("AUDIO_MIX requires a valid audio_mix_request") from exc
        assets_by_hash = {item.sha256: item for item in job.input_assets}
        if set(assets_by_hash) != {item.asset_sha256 for item in request.tracks}:
            raise ValueError("AUDIO_MIX inputs must exactly match declared tracks")
        output_directory = _local_path(job.output_prefix)
        output_directory.mkdir(parents=True, exist_ok=True)
        output = output_directory / "episode-mix.wav"
        temporary = _temporary(output)
        command: list[str | Path] = [self.ffmpeg_executable, "-nostdin", "-y"]
        filters: list[str] = []
        for index, track in enumerate(request.tracks):
            command.extend(("-i", _local_path(assets_by_hash[track.asset_sha256].uri)))
            chain = [
                f"aresample={request.sample_rate}",
                f"aformat=channel_layouts={'mono' if request.channels == 1 else 'stereo'}",
                f"volume={track.gain_db}dB",
            ]
            if track.role is MixRole.DIALOGUE and track.room_reverb > 0:
                decay = 0.05 + track.room_reverb * 0.35
                chain.append(f"aecho=0.8:0.5:40:{decay:.3f}")
            if track.start_seconds:
                delay = round(track.start_seconds * 1000)
                chain.append(f"adelay={delay}:all=1")
            filters.append(f"[{index}:a]{','.join(chain)}[a{index}]")
        inputs = "".join(f"[a{index}]" for index in range(len(request.tracks)))
        preset = request.preset
        filters.append(
            f"{inputs}amix=inputs={len(request.tracks)}:duration=longest:"
            "dropout_transition=0:normalize=0,"
            f"loudnorm=I={preset.integrated_lufs}:TP={preset.true_peak_dbfs}:"
            f"LRA={preset.loudness_range_lu},"
            f"apad=whole_dur={request.duration_seconds},"
            f"atrim=duration={request.duration_seconds}[mix]"
        )
        command.extend(
            (
                "-filter_complex",
                ";".join(filters),
                "-map",
                "[mix]",
                "-ar",
                str(request.sample_rate),
                "-ac",
                str(request.channels),
                "-c:a",
                "pcm_s16le",
                temporary,
            )
        )
        try:
            run_media_process(command, timeout_seconds=self.timeout_seconds)
            temporary.replace(output)
        finally:
            temporary.unlink(missing_ok=True)
        probe = probe_media(output, require_video=False)
        if abs(probe.duration_seconds - request.duration_seconds) > 0.05:
            raise ValueError("mixed audio duration differs from episode by more than 50 ms")
        measured_lufs, measured_peak = self._measure_loudness(output, request)
        if abs(measured_lufs - preset.integrated_lufs) > 1:
            raise ValueError("mixed audio integrated loudness misses preset by more than 1 LU")
        if measured_peak > preset.true_peak_dbfs + 0.2:
            raise ValueError("mixed audio true peak exceeds preset tolerance")
        asset = _asset(
            output,
            "audio/wav",
            {
                "mix_preset": preset.name,
                "integrated_lufs": preset.integrated_lufs,
                "true_peak_dbfs": preset.true_peak_dbfs,
                "measured_integrated_lufs": measured_lufs,
                "measured_true_peak_dbfs": measured_peak,
                "duration_seconds": probe.duration_seconds,
            },
        )
        return _result(
            job,
            [asset],
            "EPISODE_AUDIO_MIX",
            {
                "preset": preset.model_dump(),
                "track_count": len(request.tracks),
                "duration_seconds": probe.duration_seconds,
            },
            request.tracks[0].asset_sha256,
        )

    def _measure_loudness(
        self, output: Path, request: AudioMixRequest
    ) -> tuple[float, float]:
        preset = request.preset
        result = run_media_process(
            [
                self.ffmpeg_executable,
                "-nostdin",
                "-i",
                output,
                "-af",
                f"loudnorm=I={preset.integrated_lufs}:TP={preset.true_peak_dbfs}:"
                f"LRA={preset.loudness_range_lu}:print_format=json",
                "-f",
                "null",
                "-",
            ],
            timeout_seconds=self.timeout_seconds,
        )
        start = result.stderr.rfind("{")
        end = result.stderr.rfind("}")
        if start < 0 or end <= start:
            raise ValueError("FFmpeg did not return loudness measurement evidence")
        try:
            evidence = json.loads(result.stderr[start : end + 1])
            return float(evidence["input_i"]), float(evidence["input_tp"])
        except (KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
            raise ValueError("FFmpeg returned invalid loudness measurement evidence") from exc

    def _assemble(self, job: StageJob) -> StageResult:
        try:
            request = EpisodeAssemblyRequest.model_validate(
                job.params["episode_assembly_request"]
            )
        except (KeyError, ValueError) as exc:
            raise ValueError(
                "ASSEMBLE_EPISODE requires a valid episode_assembly_request"
            ) from exc
        assets = {item.sha256: item for item in job.input_assets}
        expected = {request.source_video_sha256, request.mixed_audio_sha256}
        if request.subtitle_sha256:
            expected.add(request.subtitle_sha256)
        if set(assets) != expected:
            raise ValueError("ASSEMBLE_EPISODE inputs do not match declared assets")
        source_video = _local_path(assets[request.source_video_sha256].uri)
        mixed_audio = _local_path(assets[request.mixed_audio_sha256].uri)
        subtitle = (
            _local_path(assets[request.subtitle_sha256].uri)
            if request.subtitle_sha256
            else None
        )
        output_directory = _local_path(job.output_prefix)
        output_directory.mkdir(parents=True, exist_ok=True)
        output = output_directory / "episode-master.mp4"
        temporary = _temporary(output)
        video_filter = (
            f"scale={request.width}:{request.height}:force_original_aspect_ratio=decrease,"
            f"pad={request.width}:{request.height}:(ow-iw)/2:(oh-ih)/2,"
            f"fps={request.fps},format=yuv420p"
        )
        video_codec = {"h264": "libx264", "h265": "libx265", "av1": "libaom-av1"}[
            request.video_codec
        ]
        audio_codec = {"aac": "aac", "opus": "libopus"}[request.audio_codec]
        command: list[str | Path] = [
            self.ffmpeg_executable,
            "-nostdin",
            "-y",
            "-i",
            source_video,
            "-i",
            mixed_audio,
        ]
        video_arguments: list[str] = ["-vf", video_filter, "-map", "0:v:0"]
        if request.burn_subtitles and subtitle is not None:
            assert request.subtitle_document is not None
            overlays = _render_subtitle_overlays(
                request.subtitle_document,
                output_directory / "subtitle-overlays",
                request.width,
                request.height,
                job.params.get("subtitle_font_path"),
            )
            for overlay in overlays:
                command.extend(("-loop", "1", "-i", overlay))
            filter_parts = [f"[0:v]{video_filter}[v0]"]
            current = "v0"
            for index, (cue, _) in enumerate(
                zip(request.subtitle_document.cues, overlays, strict=True), 1
            ):
                output_label = f"v{index}"
                filter_parts.append(
                    f"[{current}][{index + 1}:v]overlay=0:0:"
                    f"enable='between(t,{cue.start_seconds},{cue.end_seconds})'"
                    f"[{output_label}]"
                )
                current = output_label
            video_arguments = [
                "-filter_complex",
                ";".join(filter_parts),
                "-map",
                f"[{current}]",
            ]
        try:
            run_media_process(
                command
                + video_arguments
                + [
                    "-map",
                    "1:a:0",
                    "-c:v",
                    video_codec,
                    "-preset",
                    "medium",
                    "-crf",
                    "18",
                    "-c:a",
                    audio_codec,
                    "-b:a",
                    "192k",
                    "-t",
                    str(request.duration_seconds),
                    "-movflags",
                    "+faststart",
                    temporary,
                ],
                timeout_seconds=self.timeout_seconds,
            )
            temporary.replace(output)
        finally:
            temporary.unlink(missing_ok=True)
        probe = probe_media(output)
        if not probe.audio_streams:
            raise ValueError("episode master is missing its mixed audio stream")
        if abs(probe.duration_seconds - request.duration_seconds) > 0.05:
            raise ValueError("episode master duration differs from source by more than 50 ms")
        video = probe.video_streams[0]
        if video.width != request.width or video.height != request.height:
            raise ValueError("episode master dimensions do not match output spec")
        asset = _asset(
            output,
            "video/mp4",
            {
                "duration_seconds": probe.duration_seconds,
                "width": video.width,
                "height": video.height,
                "fps": video.frame_rate,
                "video_codec": video.codec_name,
                "audio_codec": probe.audio_streams[0].codec_name,
                "burned_subtitles": request.burn_subtitles,
            },
        )
        return _result(
            job,
            [asset],
            "EPISODE_MASTER",
            {"output": asset.metadata},
            request.source_video_sha256,
        )

    def _picture_conform(self, job: StageJob) -> StageResult:
        try:
            request = PictureConformRequest.model_validate(
                job.params["picture_conform_request"]
            )
        except (KeyError, ValueError) as exc:
            raise ValueError(
                "PICTURE_CONFORM requires a valid picture_conform_request"
            ) from exc
        assets = {item.sha256: item for item in job.input_assets}
        expected = {request.source_video_sha256} | {
            item.replacement_sha256 for item in request.edits
        }
        if set(assets) != expected:
            raise ValueError("PICTURE_CONFORM inputs do not match declared assets")
        source = _local_path(assets[request.source_video_sha256].uri)
        source_probe = probe_media(source)
        if abs(source_probe.duration_seconds - request.duration_seconds) > 0.05:
            raise ValueError("picture source duration differs from request by more than 50 ms")
        video = source_probe.video_streams[0]
        if video.width is None or video.height is None:
            raise ValueError("picture source has no usable dimensions")
        fps = video.frame_rate or 24
        output_directory = _local_path(job.output_prefix)
        output_directory.mkdir(parents=True, exist_ok=True)
        output = output_directory / "picture-master.mp4"
        temporary = _temporary(output)
        command: list[str | Path] = [self.ffmpeg_executable, "-nostdin", "-y", "-i", source]
        for edit in request.edits:
            replacement = _local_path(assets[edit.replacement_sha256].uri)
            replacement_probe = probe_media(replacement)
            edit_duration = edit.end_seconds - edit.start_seconds
            if replacement_probe.duration_seconds + 0.05 < edit_duration:
                raise ValueError("picture replacement is shorter than its authoritative shot")
            command.extend(("-i", replacement))
        filters: list[str] = []
        segment_labels: list[str] = []
        cursor = 0.0
        segment_no = 0
        for input_index, edit in enumerate(request.edits, 1):
            if edit.start_seconds > cursor:
                label = f"seg{segment_no}"
                filters.append(
                    f"[0:v]trim=start={cursor}:end={edit.start_seconds},"
                    f"setpts=PTS-STARTPTS[{label}]"
                )
                segment_labels.append(label)
                segment_no += 1
            label = f"seg{segment_no}"
            edit_duration = edit.end_seconds - edit.start_seconds
            filters.append(
                f"[{input_index}:v]trim=duration={edit_duration},"
                f"scale={video.width}:{video.height}:force_original_aspect_ratio=decrease,"
                f"pad={video.width}:{video.height}:(ow-iw)/2:(oh-ih)/2,"
                f"fps={fps},setsar=1,setpts=PTS-STARTPTS[{label}]"
            )
            segment_labels.append(label)
            segment_no += 1
            cursor = edit.end_seconds
        if cursor < request.duration_seconds:
            label = f"seg{segment_no}"
            filters.append(
                f"[0:v]trim=start={cursor}:end={request.duration_seconds},"
                f"setpts=PTS-STARTPTS[{label}]"
            )
            segment_labels.append(label)
        inputs = "".join(f"[{item}]" for item in segment_labels)
        filters.append(f"{inputs}concat=n={len(segment_labels)}:v=1:a=0[outv]")
        command.extend(
            (
                "-filter_complex",
                ";".join(filters),
                "-map",
                "[outv]",
                "-an",
                "-c:v",
                "libx264",
                "-preset",
                "medium",
                "-crf",
                "12",
                "-pix_fmt",
                "yuv420p",
                "-movflags",
                "+faststart",
                temporary,
            )
        )
        try:
            run_media_process(command, timeout_seconds=self.timeout_seconds)
            temporary.replace(output)
        finally:
            temporary.unlink(missing_ok=True)
        conformed = probe_media(output)
        if abs(conformed.duration_seconds - request.duration_seconds) > 0.05:
            raise ValueError("picture master duration differs from source by more than 50 ms")
        asset = _asset(
            output,
            "video/mp4",
            {
                "duration_seconds": conformed.duration_seconds,
                "width": conformed.video_streams[0].width,
                "height": conformed.video_streams[0].height,
                "fps": conformed.video_streams[0].frame_rate,
                "edit_count": len(request.edits),
                "adopted_shot_ids": [item.shot_id for item in request.edits],
            },
        )
        return _result(
            job,
            [asset],
            "EPISODE_PICTURE_MASTER",
            {
                "duration_seconds": conformed.duration_seconds,
                "edits": [item.model_dump() for item in request.edits],
            },
            request.source_video_sha256,
        )

    def _shot_routing(self, job: StageJob) -> StageResult:
        try:
            request = job.params["shot_routing_request"]
        except KeyError as exc:
            raise ValueError("SHOT_ROUTING requires a shot_routing_request in params") from exc

        try:
            episode_id = UUID(request["episode_id"])
        except (KeyError, TypeError, ValueError) as exc:
            raise ValueError("shot_routing_request must contain a valid episode_id") from exc

        raw_shots: list[dict] = request.get("shots") or []
        raw_persons: list[dict] = request.get("person_observations") or []
        raw_ocr: list[dict] = request.get("ocr_observations") or []
        raw_utterances: list[dict] = request.get("utterances") or []

        shot_features = tuple(
            _build_shot_features(shot, raw_persons, raw_ocr, raw_utterances)
            for shot in raw_shots
        )

        router = VisualShotRouter()
        plan: EpisodeWorkflowPlan = router.plan(episode_id, shot_features)

        output_directory = _local_path(job.output_prefix)
        output_directory.mkdir(parents=True, exist_ok=True)
        plan_path = output_directory / "workflow-plan.json"
        payload = plan.model_dump(mode="json")
        _atomic_write(plan_path, _canonical_json(payload))
        plan_asset = _asset(plan_path, "application/json", payload)

        return StageResult(
            stage_run_id=job.stage_run_id,
            stage_attempt_id=job.stage_attempt_id,
            status="OUTPUT_READY",
            variants=[VariantResult(variant_no=1, output_assets=[plan_asset])],
            domain_artifacts=[
                DomainArtifact(
                    document_type="WORKFLOW_PLAN",
                    episode_id=job.episode_id,
                    source_asset_sha256=plan_asset.sha256,
                    payload=payload,
                )
            ],
            attempt_usage={"worker": "assemble", "local": True},
        )

    def _delivery_evidence(self, job: StageJob) -> StageResult:
        try:
            request = DeliveryEvidenceRequest.model_validate(
                job.params["delivery_evidence_request"]
            )
        except (KeyError, ValueError) as exc:
            raise ValueError(
                "DELIVERY_EVIDENCE requires a valid delivery_evidence_request"
            ) from exc
        if len(job.input_assets) != 1:
            raise ValueError("DELIVERY_EVIDENCE requires exactly one master asset")
        master = job.input_assets[0]
        if master.sha256 != request.master_video_sha256 or not master.media_type.startswith(
            "video/"
        ):
            raise ValueError("DELIVERY_EVIDENCE input must be the declared master video")
        probe = probe_media(_local_path(master.uri))
        duration_ms = round(probe.duration_seconds * 1000)
        if abs(duration_ms - request.duration_ms) > 50:
            raise ValueError("delivery master duration differs from episode by more than 50 ms")
        video = probe.video_streams[0]
        if not probe.audio_streams:
            raise ValueError("delivery master is missing an audio stream")
        measured_qc = (
            QcEvidence(
                metric_name="master_duration",
                metric_version="vtv.delivery.v1",
                evaluator_release="ffprobe",
                score=1,
                verdict="PASS",
            ),
            QcEvidence(
                metric_name="master_stream_integrity",
                metric_version="vtv.delivery.v1",
                evaluator_release="ffprobe",
                score=1,
                verdict="PASS",
            ),
        )
        qc = (*request.qc, *measured_qc)
        final_encoding = {
            **request.final_encoding,
            "duration_ms": duration_ms,
            "width": video.width,
            "height": video.height,
            "fps": video.frame_rate,
            "video_codec": video.codec_name,
            "audio_codec": probe.audio_streams[0].codec_name,
        }
        quality = {
            "schema_version": "vtv.quality-report.v1",
            "source_video_sha256": request.source_video_sha256,
            "master_video_sha256": request.master_video_sha256,
            "project_state_version": request.project_state_version,
            "qc": [item.model_dump(mode="json") for item in qc],
            "edit_chain": [item.model_dump(mode="json") for item in request.edit_chain],
            "models": [item.model_dump(mode="json") for item in request.models],
            "cost": request.cost.model_dump(mode="json"),
            "final_encoding": final_encoding,
        }
        shot_list = {
            "schema_version": "vtv.shot-list.v1",
            "source_video_sha256": request.source_video_sha256,
            "master_video_sha256": request.master_video_sha256,
            "duration_ms": request.duration_ms,
            "shots": [item.model_dump(mode="json") for item in request.shots],
        }
        output_directory = _local_path(job.output_prefix)
        output_directory.mkdir(parents=True, exist_ok=True)
        quality_path = output_directory / "quality-report.json"
        shots_path = output_directory / "shot-list.json"
        _atomic_write(quality_path, _canonical_json(quality))
        _atomic_write(shots_path, _canonical_json(shot_list))
        quality_asset = _asset(quality_path, "application/json", quality)
        shots_asset = _asset(shots_path, "application/json", shot_list)
        return StageResult(
            stage_run_id=job.stage_run_id,
            stage_attempt_id=job.stage_attempt_id,
            status="OUTPUT_READY",
            variants=[
                VariantResult(
                    variant_no=1,
                    output_assets=[quality_asset, shots_asset],
                )
            ],
            domain_artifacts=[
                DomainArtifact(
                    document_type="QUALITY_REPORT",
                    episode_id=job.episode_id,
                    source_asset_sha256=quality_asset.sha256,
                    payload=quality,
                ),
                DomainArtifact(
                    document_type="DELIVERY_SHOT_LIST",
                    episode_id=job.episode_id,
                    source_asset_sha256=shots_asset.sha256,
                    payload=shot_list,
                ),
            ],
            attempt_usage={"worker": "assemble", "local": True},
        )


def _build_shot_features(
    shot: dict,
    persons: list[dict],
    ocr: list[dict],
    utterances: list[dict],
) -> ShotVisualFeatures:
    """Aggregate per-shot visual/audio features from raw observation lists."""
    shot_id = UUID(shot["shot_id"])
    shot_no: int = int(shot["shot_no"])
    start_ms: int = int(shot.get("start_ms", 0))
    end_ms: int = int(shot.get("end_ms", start_ms + 1))
    duration_ms: int = end_ms - start_ms

    start_s = start_ms / 1000.0
    end_s = end_ms / 1000.0

    # PersonObservation fields: start_seconds, end_seconds, face_visible, box (w*h = face area)
    shot_persons = [
        p
        for p in persons
        if float(p.get("end_seconds", 0)) > start_s
        and float(p.get("start_seconds", 0)) < end_s
    ]
    person_count = len({p.get("track_id", p.get("observation_id", "")) for p in shot_persons})
    has_face_visible = any(p.get("face_visible", False) for p in shot_persons)
    max_face_scale = 0.0
    max_occlusion = 0.0
    for p in shot_persons:
        box = p.get("box") or {}
        w = float(box.get("width", 0))
        h = float(box.get("height", 0))
        max_face_scale = max(max_face_scale, w * h)
    # max_occlusion not directly available in PersonObservation; default to 0

    # OcrObservation: detect non-Latin script overlays
    shot_ocr = [
        o
        for o in ocr
        if float(o.get("end_seconds", 0)) > start_s
        and float(o.get("start_seconds", 0)) < end_s
    ]
    has_text_overlay = any(
        o.get("script") not in (None, "Latin", "latin") for o in shot_ocr
    )

    # Utterances: detect dialogue overlapping this shot
    shot_utterances = [
        u
        for u in utterances
        if float(u.get("end_seconds", 0)) > start_s
        and float(u.get("start_seconds", 0)) < end_s
    ]
    has_dialogue = len(shot_utterances) > 0
    dialogue_duration_seconds = sum(
        min(float(u.get("end_seconds", start_s)), end_s)
        - max(float(u.get("start_seconds", end_s)), start_s)
        for u in shot_utterances
    )

    return ShotVisualFeatures(
        shot_id=shot_id,
        shot_no=shot_no,
        start_ms=start_ms,
        end_ms=end_ms,
        duration_ms=duration_ms,
        person_count=person_count,
        has_face_visible=has_face_visible,
        max_face_scale=min(max_face_scale, 1.0),
        max_occlusion=max_occlusion,
        has_text_overlay=has_text_overlay,
        has_dialogue=has_dialogue,
        dialogue_duration_seconds=max(dialogue_duration_seconds, 0.0),
        has_background_replacement_needed=bool(
            shot.get("has_background_replacement_needed", False)
        ),
        full_regen_required=bool(shot.get("full_regen_required", False)),
        primary_scene_label=str(shot.get("primary_scene_label", "")),
    )


def _result(
    job: StageJob,
    assets: list[AssetRef],
    document_type: str,
    payload: dict,
    source_hash: str,
) -> StageResult:
    return StageResult(
        stage_run_id=job.stage_run_id,
        stage_attempt_id=job.stage_attempt_id,
        status="OUTPUT_READY",
        variants=[VariantResult(variant_no=1, output_assets=assets)],
        domain_artifacts=[
            DomainArtifact(
                document_type=document_type,
                episode_id=job.episode_id,
                source_asset_sha256=source_hash,
                payload=payload,
            )
        ],
        attempt_usage={"worker": "assemble", "local": True},
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
        raise ValueError("assemble worker requires local file URIs")
    return Path(unquote(parsed.path if parsed.scheme else uri))


def _temporary(output: Path) -> Path:
    return output.with_name(f".{output.stem}.{uuid4().hex}.part{output.suffix}")


def _atomic_write(path: Path, content: bytes) -> None:
    temporary = _temporary(path)
    try:
        temporary.write_bytes(content)
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)


def _canonical_json(value: dict) -> bytes:
    content = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return f"{content}\n".encode()


def _render_subtitle_overlays(
    document: SubtitleDocument,
    output_directory: Path,
    width: int,
    height: int,
    configured_font: str | None,
) -> tuple[Path, ...]:
    output_directory.mkdir(parents=True, exist_ok=True)
    font_size = max(20, round(height * 0.038))
    font = _font(font_size, configured_font)
    paths: list[Path] = []
    for cue in document.cues:
        image = Image.new("RGBA", (width, height), (0, 0, 0, 0))
        draw = ImageDraw.Draw(image)
        lines = _wrap_text(draw, cue.text.strip(), font, width * 0.82)
        spacing = max(4, round(font_size * 0.22))
        boxes = [draw.textbbox((0, 0), line, font=font) for line in lines]
        line_heights = [box[3] - box[1] for box in boxes]
        text_height = sum(line_heights) + spacing * max(0, len(lines) - 1)
        padding = max(8, round(font_size * 0.35))
        y = height - round(height * 0.09) - text_height - padding * 2
        draw.rounded_rectangle(
            (width * 0.06, y, width * 0.94, y + text_height + padding * 2),
            radius=padding,
            fill=(0, 0, 0, 170),
        )
        cursor = y + padding
        for line, box, line_height in zip(lines, boxes, line_heights, strict=True):
            line_width = box[2] - box[0]
            draw.text(
                ((width - line_width) / 2, cursor),
                line,
                font=font,
                fill=(255, 255, 255, 255),
                stroke_width=max(1, font_size // 20),
                stroke_fill=(0, 0, 0, 230),
            )
            cursor += line_height + spacing
        path = output_directory / f"cue-{cue.index:04d}.png"
        image.save(path, format="PNG")
        paths.append(path)
    return tuple(paths)


def _font(size: int, configured: str | None) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    candidates = (
        configured,
        "/System/Library/Fonts/Supplemental/Arial Unicode.ttf",
        "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    )
    for candidate in candidates:
        if candidate and Path(candidate).is_file():
            return ImageFont.truetype(candidate, size=size)
    return ImageFont.load_default(size=size)


def _wrap_text(
    draw: ImageDraw.ImageDraw,
    text: str,
    font: ImageFont.FreeTypeFont | ImageFont.ImageFont,
    max_width: float,
) -> tuple[str, ...]:
    lines: list[str] = []
    current = ""
    for character in text:
        candidate = current + character
        if current and draw.textlength(candidate, font=font) > max_width:
            lines.append(current.rstrip())
            current = character.lstrip()
        else:
            current = candidate
    if current:
        lines.append(current.rstrip())
    return tuple(lines or (" ",))
