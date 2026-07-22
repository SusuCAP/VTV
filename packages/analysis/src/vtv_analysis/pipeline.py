from dataclasses import dataclass

from .contracts import AsrAdapter, AudioAnalysis, DiarizationAdapter, VadAdapter


@dataclass(frozen=True, slots=True)
class AudioAnalysisPipeline:
    vad: VadAdapter
    asr: AsrAdapter
    diarization: DiarizationAdapter

    def analyze(
        self,
        audio_uri: str,
        duration_seconds: float,
        language_hint: str | None = None,
    ) -> AudioAnalysis:
        speech = self.vad.detect(audio_uri, duration_seconds)
        transcript = self.asr.transcribe(audio_uri, speech, language_hint)
        speakers = self.diarization.identify(audio_uri, speech)
        language = transcript[0].language if transcript else (language_hint or "und")
        return AudioAnalysis(
            duration_seconds=duration_seconds,
            language=language,
            speech=speech,
            transcript=transcript,
            speakers=speakers,
        )
