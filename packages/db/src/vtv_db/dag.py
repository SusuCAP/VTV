from dataclasses import dataclass
from uuid import UUID


@dataclass(frozen=True, slots=True)
class StageDefinition:
    key: str
    stage_type: str
    runtime_profile_id: str
    depends_on: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class ScopedStageDefinition(StageDefinition):
    episode_id: UUID | None = None


def build_project_analysis_dag(
    episode_ids: tuple[UUID, ...],
) -> tuple[ScopedStageDefinition, ...]:
    if not episode_ids:
        raise ValueError("project analysis requires at least one episode")
    definitions: list[ScopedStageDefinition] = []
    synthesis_dependencies: list[str] = []
    for episode_id in episode_ids:
        prefix = f"episode:{episode_id}"
        ingest = f"{prefix}:ingest"
        proxy = f"{prefix}:proxy"
        shots = f"{prefix}:shots"
        stems = f"{prefix}:audio-stems"
        asr = f"{prefix}:asr"
        vision = f"{prefix}:vision"
        definitions.extend(
            (
                ScopedStageDefinition(
                    ingest, "INGEST_VALIDATE", "cpu-media", episode_id=episode_id
                ),
                ScopedStageDefinition(proxy, "PROXY_GENERATE", "cpu-media", (ingest,), episode_id),
                ScopedStageDefinition(
                    shots, "SHOT_DETECT", "gpu-analysis-light", (proxy,), episode_id
                ),
                ScopedStageDefinition(
                    stems, "AUDIO_STEM_SEPARATION", "gpu-audio", (proxy,), episode_id
                ),
                ScopedStageDefinition(asr, "ASR_ALIGN", "gpu-audio", (stems,), episode_id),
                ScopedStageDefinition(
                    vision, "VISION_ANALYSIS", "gpu-analysis", (proxy, shots), episode_id
                ),
            )
        )
        synthesis_dependencies.extend((asr, vision))
    definitions.append(
        ScopedStageDefinition(
            "synthesis",
            "PROJECT_SYNTHESIS",
            "gpu-analysis",
            tuple(synthesis_dependencies),
        )
    )
    result = tuple(definitions)
    validate_dag(result)
    return result


EPISODE_INGEST_DAG: tuple[StageDefinition, ...] = (
    StageDefinition("ingest", "INGEST_VALIDATE", "cpu-media"),
)


def validate_dag(definitions: tuple[StageDefinition, ...]) -> None:
    keys = [stage.key for stage in definitions]
    if len(keys) != len(set(keys)):
        raise ValueError("stage keys must be unique")
    seen: set[str] = set()
    for stage in definitions:
        missing = set(stage.depends_on) - seen
        if missing:
            raise ValueError(f"stage {stage.key} has unresolved dependencies: {sorted(missing)}")
        seen.add(stage.key)
