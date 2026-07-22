from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class StageDefinition:
    key: str
    stage_type: str
    runtime_profile_id: str
    depends_on: tuple[str, ...] = ()


PROJECT_ANALYSIS_DAG: tuple[StageDefinition, ...] = (
    StageDefinition("ingest", "INGEST_VALIDATE", "cpu-media"),
    StageDefinition("proxy", "PROXY_GENERATE", "cpu-media", ("ingest",)),
    StageDefinition("shots", "SHOT_DETECT", "gpu-analysis-light", ("proxy",)),
    StageDefinition("asr", "ASR_ALIGN", "gpu-audio", ("proxy",)),
    StageDefinition("vision", "VISION_ANALYSIS", "gpu-analysis", ("shots",)),
    StageDefinition(
        "synthesis",
        "PROJECT_SYNTHESIS",
        "gpu-analysis",
        ("asr", "vision"),
    ),
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
