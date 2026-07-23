from __future__ import annotations

from pydantic import BaseModel, Field


class ConcurrencyPolicy(BaseModel):
    """Per-project concurrency limits for production dispatch."""

    max_concurrent_episodes: int = Field(default=3, ge=1, le=20)
    max_concurrent_visual_stages: int = Field(default=8, ge=1, le=50)
    max_concurrent_tts_stages: int = Field(default=10, ge=1, le=100)
    max_concurrent_lipsync_stages: int = Field(default=5, ge=1, le=30)
    max_concurrent_assembly_stages: int = Field(default=2, ge=1, le=10)
    priority_episodes: tuple[int, ...] = ()  # episode_no list; dispatch first

    def get_stage_limit(self, stage_type: str) -> int:
        """Return the concurrency limit for the given stage type."""
        if stage_type.startswith("VISUAL_"):
            return self.max_concurrent_visual_stages
        if stage_type == "TTS_GENERATE":
            return self.max_concurrent_tts_stages
        if stage_type == "LIPSYNC_GENERATE":
            return self.max_concurrent_lipsync_stages
        if stage_type in ("ASSEMBLE_EPISODE", "PICTURE_CONFORM", "AUDIO_MIX"):
            return self.max_concurrent_assembly_stages
        return 20  # default high limit


DEFAULT_CONCURRENCY_POLICY = ConcurrencyPolicy()
