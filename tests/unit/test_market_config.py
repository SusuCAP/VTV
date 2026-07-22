from __future__ import annotations

import pytest
from pydantic import ValidationError
from vtv_markets import (
    BUILTIN_MARKETS,
    CulturalRule,
    LocalizationRuleSet,
    MarketConfig,
    get_market_config,
    list_markets,
)
from vtv_schemas.retention import DEFAULT_RETENTION_POLICY, RetentionPolicy, RetentionRule

# --- MarketConfig field validation ---


def test_market_config_max_subtitle_cps_lower_bound():
    with pytest.raises(ValidationError):
        MarketConfig(
            market_code="xx-XX",
            language_code="xx",
            display_name="Test",
            max_subtitle_cps=9,  # below ge=10
        )


def test_market_config_max_subtitle_cps_upper_bound():
    with pytest.raises(ValidationError):
        MarketConfig(
            market_code="xx-XX",
            language_code="xx",
            display_name="Test",
            max_subtitle_cps=26,  # above le=25
        )


def test_market_config_max_subtitle_cps_valid():
    cfg = MarketConfig(
        market_code="xx-XX",
        language_code="xx",
        display_name="Test",
        max_subtitle_cps=15,
    )
    assert cfg.max_subtitle_cps == 15


# --- CulturalRule category validation ---


def test_cultural_rule_valid_category():
    rule = CulturalRule(
        rule_id="test-rule",
        category="currency",
        source_pattern=r"\$",
        target_replacement="USD",
    )
    assert rule.category == "currency"


def test_cultural_rule_invalid_category():
    with pytest.raises(ValidationError):
        CulturalRule(
            rule_id="bad-cat",
            category="invalid_category",  # not in Literal
            source_pattern=r"\$",
            target_replacement="",
        )


# --- LocalizationRuleSet forbidden_terms ---


def test_localization_ruleset_forbidden_terms():
    rs = LocalizationRuleSet(
        ruleset_id="test-rs",
        version="1.0",
        source_market="zh-CN",
        target_market="en-US",
        forbidden_terms=("bad-word", "another"),
    )
    assert "bad-word" in rs.forbidden_terms
    assert len(rs.forbidden_terms) == 2


# --- get_market_config ---


def test_get_market_config_known():
    cfg = get_market_config("en-US")
    assert isinstance(cfg, MarketConfig)
    assert cfg.market_code == "en-US"


def test_get_market_config_unknown_raises():
    with pytest.raises(KeyError):
        get_market_config("zz-ZZ")


# --- list_markets ---


def test_list_markets_returns_sorted():
    markets = list_markets()
    assert markets == sorted(markets)


# --- All 5 builtin markets accessible ---


def test_all_builtin_markets_accessible():
    expected = {"en-US", "en-GB", "es-US", "ko-KR", "ja-JP"}
    assert set(BUILTIN_MARKETS.keys()) == expected
    for code in expected:
        cfg = get_market_config(code)
        assert cfg.market_code == code


# --- en-US ruleset has cultural rules ---


def test_en_us_ruleset_has_cultural_rules():
    cfg = get_market_config("en-US")
    assert cfg.ruleset is not None
    assert len(cfg.ruleset.cultural_rules) > 0
    rule_ids = {r.rule_id for r in cfg.ruleset.cultural_rules}
    assert "currency_rmb" in rule_ids


# --- RetentionPolicy.get_retain_days ---


def test_retention_policy_get_retain_days_lookup():
    policy = RetentionPolicy(
        policy_key="test",
        rules=(
            RetentionRule(asset_type="proxy_video", retain_days=30),
            RetentionRule(asset_type="subtitle", retain_days=None),
        ),
    )
    assert policy.get_retain_days("proxy_video") == 30
    assert policy.get_retain_days("subtitle") is None


# --- DEFAULT_RETENTION_POLICY has all asset types ---


def test_default_retention_policy_has_all_asset_types():
    expected_types = {
        "source_video",
        "master_video",
        "proxy_video",
        "shot_clip",
        "render_candidate",
        "tts_candidate",
        "qc_report",
        "shot_list",
        "subtitle",
        "keyframe_preview",
    }
    actual = {r.asset_type for r in DEFAULT_RETENTION_POLICY.rules}
    assert actual == expected_types


# --- RetentionRule retain_days = None means permanent ---


def test_retention_rule_none_means_permanent():
    rule = RetentionRule(asset_type="source_video", retain_days=None)
    assert rule.retain_days is None


# --- RetentionRule retain_days = 0 means immediate ---


def test_retention_rule_zero_means_immediate():
    rule = RetentionRule(asset_type="render_candidate", retain_days=0)
    assert rule.retain_days == 0
