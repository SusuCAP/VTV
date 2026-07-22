from dataclasses import dataclass

from .contracts import SpeakerTurn, SpeechSegment, TranscriptSegment, TranscriptWord


@dataclass(frozen=True, slots=True)
class DeterministicVad:
    model_release: str = "mock-vad@1"

    def detect(self, audio_uri: str, duration_seconds: float) -> tuple[SpeechSegment, ...]:
        del audio_uri
        if duration_seconds <= 0:
            raise ValueError("duration_seconds must be positive")
        return (SpeechSegment(start_seconds=0, end_seconds=duration_seconds, confidence=1),)


@dataclass(frozen=True, slots=True)
class DeterministicAsr:
    model_release: str = "mock-asr-align@1"
    text: str = "测试台词"

    def transcribe(
        self,
        audio_uri: str,
        speech: tuple[SpeechSegment, ...],
        language_hint: str | None,
    ) -> tuple[TranscriptSegment, ...]:
        del audio_uri
        language = language_hint or "zh-CN"
        return tuple(
            TranscriptSegment(
                start_seconds=span.start_seconds,
                end_seconds=span.end_seconds,
                text=self.text,
                language=language,
                words=(
                    TranscriptWord(
                        start_seconds=span.start_seconds,
                        end_seconds=span.end_seconds,
                        text=self.text,
                        confidence=1,
                    ),
                ),
            )
            for span in speech
        )


@dataclass(frozen=True, slots=True)
class DeterministicDiarization:
    model_release: str = "mock-diarization@1"
    speaker_id: str = "speaker-001"

    def identify(
        self, audio_uri: str, speech: tuple[SpeechSegment, ...]
    ) -> tuple[SpeakerTurn, ...]:
        del audio_uri
        return tuple(
            SpeakerTurn(
                start_seconds=span.start_seconds,
                end_seconds=span.end_seconds,
                speaker_id=self.speaker_id,
                confidence=1,
            )
            for span in speech
        )
