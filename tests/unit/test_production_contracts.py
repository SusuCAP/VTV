from uuid import uuid4

import pytest
from vtv_production import (
    LipSyncDecision,
    LipSyncLevel,
    LipSyncRequest,
    ReviewedLocalizationAdapter,
    ShotDialogueFeatures,
    TieredLipSyncRouter,
    TtsRequest,
    Utterance,
    VoiceRelease,
    VoiceRightsSnapshot,
)


def _utterance(character_id: str = "character-1") -> Utterance:
    return Utterance(
        utterance_id="utterance-1",
        character_id=character_id,
        source_text="合同已经签了。",
        source_language="zh-CN",
        start_seconds=2,
        end_seconds=4,
        emotion="firm",
        protected_terms=("合同",),
    )


def _voice(character_id: str = "character-1") -> VoiceRelease:
    return VoiceRelease(
        voice_release_id=uuid4(),
        character_id=character_id,
        model_release="voxcpm2@candidate-1",
        reference_asset_sha256s=("a" * 64,),
        rights=VoiceRightsSnapshot(
            rights_release_id=uuid4(),
            state_version=1,
            subject_id=character_id,
            allowed_operations=frozenset({"voice_clone"}),
            allowed_languages=frozenset({"en-US"}),
            allowed_markets=frozenset({"US"}),
            commercial_allowed=True,
            valid_at_execution=True,
        ),
    )


def test_reviewed_localization_preserves_source_timing_and_release() -> None:
    result = ReviewedLocalizationAdapter(
        {"utterance-1": "The contract is already signed."}
    ).localize(
        (_utterance(),),
        target_language="en-US",
        target_market="US",
        localization_release="localization@4",
    )

    assert result[0].utterance.duration_seconds == 2
    assert result[0].target_text == "The contract is already signed."
    assert result[0].localization_release == "localization@4"
    assert result[0].review_state == "HUMAN_APPROVED"


def test_tts_request_requires_matching_current_rights_scope() -> None:
    localized = ReviewedLocalizationAdapter({"utterance-1": "Signed."}).localize(
        (_utterance(),),
        target_language="en-US",
        target_market="US",
        localization_release="localization@1",
    )[0]

    request = TtsRequest(localized=localized, voice_release=_voice(), seed=42)
    assert request.target_duration_seconds == 2

    with pytest.raises(ValueError, match="rights do not permit"):
        TtsRequest(
            localized=localized.model_copy(update={"target_market": "GB"}),
            voice_release=_voice(),
            seed=42,
        )
    with pytest.raises(ValueError, match="does not belong"):
        TtsRequest(localized=localized, voice_release=_voice("character-2"), seed=42)


@pytest.mark.parametrize(
    ("features", "expected"),
    (
        ({"mouth_visible": False, "face_scale": 0.3}, LipSyncLevel.L0_NONE),
        ({"mouth_visible": True, "face_scale": 0.1}, LipSyncLevel.L1_FAST),
        ({"mouth_visible": True, "face_scale": 0.3}, LipSyncLevel.L2_PRESERVE_SOURCE),
        (
            {"mouth_visible": True, "face_scale": 0.3, "occlusion": 0.6},
            LipSyncLevel.L3_GENERATIVE_FACE,
        ),
        (
            {
                "mouth_visible": True,
                "face_scale": 0.1,
                "body_visible": True,
                "dialogue_duration_seconds": 5,
            },
            LipSyncLevel.L4_FULL_BODY,
        ),
        (
            {"mouth_visible": True, "face_scale": 0.3, "full_regeneration_required": True},
            LipSyncLevel.L5_FULL_REGEN,
        ),
    ),
)
def test_tiered_lipsync_router_covers_all_levels(features: dict, expected: LipSyncLevel) -> None:
    defaults = {
        "shot_id": uuid4(),
        "mouth_visible": True,
        "face_scale": 0.1,
        "occlusion": 0,
        "body_visible": False,
        "dialogue_duration_seconds": 2,
    }

    decision = TieredLipSyncRouter().route(ShotDialogueFeatures(**(defaults | features)))

    assert decision.level == expected
    assert decision.reason_codes
    assert decision.maximum_duration_deviation in {0.04, 0.08}


def test_lipsync_request_requires_lipsync_rights_and_deterministic_l0() -> None:
    features = ShotDialogueFeatures(
        shot_id=uuid4(),
        mouth_visible=False,
        face_scale=0.03,
        occlusion=0.5,
        body_visible=False,
        dialogue_duration_seconds=2,
    )
    decision = LipSyncDecision(
        shot_id=features.shot_id,
        level=LipSyncLevel.L0_NONE,
        reason_codes=("MOUTH_NOT_VISIBLE",),
        maximum_duration_deviation=0.08,
    )
    rights = _voice().rights.model_copy(
        update={"allowed_operations": frozenset({"voice_clone", "lipsync"})}
    )
    request = LipSyncRequest(
        features=features,
        decision=decision,
        source_video_sha256="b" * 64,
        adopted_tts_variant_id=uuid4(),
        audio_sha256="c" * 64,
        target_language="en-US",
        target_market="US",
        rights=rights,
        seed=1,
        candidate_count=1,
    )
    assert request.decision.level is LipSyncLevel.L0_NONE

    with pytest.raises(ValueError, match="exactly one"):
        LipSyncRequest(**(request.model_dump() | {"candidate_count": 2}))
    with pytest.raises(ValueError, match="rights do not permit"):
        LipSyncRequest(
            **(
                request.model_dump()
                | {
                    "rights": rights.model_copy(
                        update={"allowed_operations": frozenset({"voice_clone"})}
                    )
                }
            )
        )
