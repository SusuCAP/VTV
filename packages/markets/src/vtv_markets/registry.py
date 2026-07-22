from __future__ import annotations

from .contracts import CulturalRule, LocalizationRuleSet, MarketConfig

BUILTIN_MARKETS: dict[str, MarketConfig] = {
    "en-US": MarketConfig(
        market_code="en-US",
        language_code="en",
        display_name="United States English",
        currency_code="USD",
        subtitle_format="both",
        max_subtitle_cps=17,
        dubbing_style="natural",
        lipsync_priority=True,
        content_restrictions=("no_explicit_violence", "no_minors_romance"),
        ruleset=LocalizationRuleSet(
            ruleset_id="zh-CN-to-en-US-v1",
            version="1.0",
            source_market="zh-CN",
            target_market="en-US",
            cultural_rules=(
                CulturalRule(
                    rule_id="currency_rmb",
                    category="currency",
                    source_pattern=r"元|RMB|人民币|¥",
                    target_replacement="USD",
                    notes="Replace RMB references with USD",
                ),
                CulturalRule(
                    rule_id="name_order",
                    category="name",
                    source_pattern=r"(?P<surname>[A-Za-z]{1,4})(?P<given>[A-Za-z]{2,10})",
                    target_replacement=r"Given Surname",
                    notes="Chinese surname-first order → Western given-first",
                ),
                CulturalRule(
                    rule_id="honorific_mr",
                    category="honorific",
                    source_pattern=r"先生|Mr\.?",
                    target_replacement="Mr.",
                    notes="Normalize Mr. honorific",
                ),
                CulturalRule(
                    rule_id="honorific_ms",
                    category="honorific",
                    source_pattern=r"女士|小姐|Ms\.?|Miss",
                    target_replacement="Ms.",
                    notes="Normalize Ms. honorific",
                ),
            ),
            forbidden_terms=("CCP", "Taiwan independence"),
        ),
    ),
    "en-GB": MarketConfig(
        market_code="en-GB",
        language_code="en",
        display_name="British English",
        currency_code="GBP",
        subtitle_format="both",
        max_subtitle_cps=17,
        dubbing_style="natural",
        lipsync_priority=True,
    ),
    "es-US": MarketConfig(
        market_code="es-US",
        language_code="es",
        display_name="US Spanish",
        currency_code="USD",
        subtitle_format="both",
        max_subtitle_cps=15,
        dubbing_style="natural",
        lipsync_priority=True,
    ),
    "ko-KR": MarketConfig(
        market_code="ko-KR",
        language_code="ko",
        display_name="Korean",
        currency_code="KRW",
        subtitle_format="both",
        max_subtitle_cps=12,
        dubbing_style="theatrical",
        lipsync_priority=True,
    ),
    "ja-JP": MarketConfig(
        market_code="ja-JP",
        language_code="ja",
        display_name="Japanese",
        currency_code="JPY",
        subtitle_format="both",
        max_subtitle_cps=10,
        dubbing_style="theatrical",
        lipsync_priority=True,
    ),
}


def get_market_config(market_code: str) -> MarketConfig:
    """Return MarketConfig for the given market code.
    Raises KeyError if not registered.
    """
    return BUILTIN_MARKETS[market_code]


def list_markets() -> list[str]:
    return sorted(BUILTIN_MARKETS.keys())
