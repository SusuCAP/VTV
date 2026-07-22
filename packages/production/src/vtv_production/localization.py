from dataclasses import dataclass

from .contracts import LocalizedUtterance, ReviewState, Utterance


@dataclass(frozen=True, slots=True)
class ReviewedLocalizationAdapter:
    """Uses an externally reviewed translation map without pretending to translate."""

    translations: dict[str, str]
    model_release: str = "human-reviewed-localization@1"

    def localize(
        self,
        utterances: tuple[Utterance, ...],
        *,
        target_language: str,
        target_market: str,
        localization_release: str,
    ) -> tuple[LocalizedUtterance, ...]:
        missing = [
            item.utterance_id
            for item in utterances
            if item.utterance_id not in self.translations
        ]
        if missing:
            raise ValueError(f"reviewed translations missing utterances: {missing}")
        return tuple(
            LocalizedUtterance(
                utterance=item,
                target_text=self.translations[item.utterance_id],
                target_language=target_language,
                target_market=target_market,
                localization_release=localization_release,
                review_state=ReviewState.HUMAN_APPROVED,
            )
            for item in utterances
        )
