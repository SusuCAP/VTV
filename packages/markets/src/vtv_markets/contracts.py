from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class CulturalRule(BaseModel):
    model_config = ConfigDict(frozen=True)
    rule_id: str = Field(min_length=1, max_length=64)
    category: Literal["name", "honorific", "currency", "idiom", "location", "unit"]
    source_pattern: str = Field(min_length=1)  # regex or keyword to match
    target_replacement: str = Field(min_length=0)  # empty means remove
    confidence: float = Field(ge=0, le=1, default=1.0)
    notes: str = Field(default="", max_length=500)


class LocalizationRuleSet(BaseModel):
    model_config = ConfigDict(frozen=True)
    ruleset_id: str = Field(min_length=1, max_length=64)
    version: str = Field(min_length=1, max_length=32)
    source_market: str = Field(min_length=2, max_length=16)  # e.g. "zh-CN"
    target_market: str = Field(min_length=2, max_length=16)  # e.g. "en-US"
    cultural_rules: tuple[CulturalRule, ...] = ()
    forbidden_terms: tuple[str, ...] = ()  # must not appear in output
    preferred_style: str = Field(default="natural", pattern=r"^(natural|formal|casual)$")


class MarketConfig(BaseModel):
    model_config = ConfigDict(frozen=True)
    market_code: str = Field(min_length=2, max_length=16)  # e.g. "en-US"
    language_code: str = Field(min_length=2, max_length=35)  # e.g. "en"
    display_name: str = Field(min_length=1, max_length=100)
    currency_code: str = Field(pattern=r"^[A-Z]{3}$", default="USD")
    content_restrictions: tuple[str, ...] = ()  # platform rules
    subtitle_format: Literal["srt", "vtt", "both"] = "both"
    max_subtitle_cps: int = Field(default=17, ge=10, le=25)  # chars/sec
    dubbing_style: Literal["natural", "neutral", "theatrical"] = "natural"
    lipsync_priority: bool = True  # require lip-sync for close-ups
    ruleset: LocalizationRuleSet | None = None
