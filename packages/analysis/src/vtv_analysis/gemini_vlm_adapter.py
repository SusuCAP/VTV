"""Gemini / Qwen3-VL-235B VLM project understanding adapter (P12-B).

Drives cross-episode plot/entity extraction for the PROJECT_SYNTHESIS stage.
Supports two backends:
  - Gemini 3.1 Pro (via Google Generative AI SDK)
  - Qwen3-VL-235B self-hosted (via vLLM / SGLang HTTP endpoint)

Outputs structured JSON that maps directly onto the Localization Bible and
Anchor Pack schemas consumed by the synthesis worker.

All heavy imports are lazy so the class can be imported in CI without GPU.

Env vars:
    VTV_VLM_BACKEND              – gemini | qwen3_vl_235b | qwen3_vl (default: gemini)
    VTV_GEMINI_API_KEY           – Google AI API key (required for gemini backend)
    VTV_GEMINI_MODEL_ID          – model ID (default: gemini-3.1-pro-preview)
    VTV_QWEN_VLM_ENDPOINT        – HTTP base URL for Qwen3-VL-235B vLLM endpoint
    VTV_QWEN_VLM_API_KEY         – API key for vLLM endpoint (optional)
    VTV_VLM_TIMEOUT              – request timeout seconds (default: 120)
"""
from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True, slots=True)
class GeminiVLMAdapter:
    """VLM project understanding adapter for cross-episode analysis.

    Accepts a batch of evidence items (transcript excerpts + keyframe URIs)
    and returns structured JSON covering:
      - character_relationships: list of {subject, relation, object, evidence}
      - cultural_exposures: list of {category, description, timecodes, severity}
      - entities: list of {type, source_name, context, timecodes}
      - plot_events: list of {description, characters, timecodes}
    """

    _release: str = field(default="gemini-vlm@1")

    @property
    def model_release(self) -> str:  # noqa: D102
        return self._release

    def extract_project_understanding(
        self,
        *,
        episodes_context: list[dict[str, Any]],
        target_market: str,
        max_characters: int = 20,
    ) -> dict[str, Any]:
        """Run cross-episode VLM analysis and return structured understanding dict.

        Args:
            episodes_context: list of per-episode dicts with keys:
                episode_no, transcript_excerpt, scene_descriptions, shot_timecodes
            target_market: e.g. "en-US"
            max_characters: maximum number of characters to track

        Returns:
            dict with keys: character_relationships, cultural_exposures,
            entities, plot_events, model_release
        """
        backend = os.environ.get("VTV_VLM_BACKEND", "gemini")

        if backend == "gemini":
            result = _call_gemini(episodes_context, target_market, max_characters)
        elif backend in ("qwen3_vl_235b", "qwen3_vl"):
            result = _call_qwen_vllm(episodes_context, target_market, max_characters)
        else:
            raise ValueError(
                f"Unknown VLM backend: {backend!r}. "
                "Set VTV_VLM_BACKEND to 'gemini' or 'qwen3_vl_235b'."
            )

        result["model_release"] = self.model_release
        return result


# ── Gemini backend ────────────────────────────────────────────────────────────

def _call_gemini(
    episodes_context: list[dict[str, Any]],
    target_market: str,
    max_characters: int,
) -> dict[str, Any]:
    """Call Gemini 3.1 Pro via Google Generative AI SDK."""
    try:
        import google.generativeai as genai  # type: ignore[import]
    except ImportError:
        raise ImportError(
            "google-generativeai is not installed. "
            "Run: pip install google-generativeai"
        ) from None

    api_key = os.environ.get("VTV_GEMINI_API_KEY", "")
    if not api_key:
        raise RuntimeError("VTV_GEMINI_API_KEY is not set.")

    model_id = os.environ.get("VTV_GEMINI_MODEL_ID", "gemini-3.1-pro-preview")

    genai.configure(api_key=api_key)
    model = genai.GenerativeModel(model_id)

    prompt = _build_prompt(episodes_context, target_market, max_characters)

    response = model.generate_content(
        prompt,
        generation_config=genai.GenerationConfig(
            response_mime_type="application/json",
            max_output_tokens=8192,
        ),
    )

    return _parse_vlm_response(response.text)


# ── Qwen3-VL-235B vLLM backend ────────────────────────────────────────────────

def _call_qwen_vllm(
    episodes_context: list[dict[str, Any]],
    target_market: str,
    max_characters: int,
) -> dict[str, Any]:
    """Call Qwen3-VL-235B via a vLLM/SGLang OpenAI-compatible endpoint."""
    import httpx

    endpoint = os.environ.get("VTV_QWEN_VLM_ENDPOINT", "").rstrip("/")
    if not endpoint:
        raise RuntimeError(
            "VTV_QWEN_VLM_ENDPOINT is not set. "
            "Point it to a running Qwen3-VL-235B vLLM endpoint."
        )
    api_key = os.environ.get("VTV_QWEN_VLM_API_KEY", "")
    timeout = float(os.environ.get("VTV_VLM_TIMEOUT", "120"))

    headers = {"Content-Type": "application/json"}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"

    prompt = _build_prompt(episodes_context, target_market, max_characters)

    payload = {
        "model": "Qwen/Qwen3-VL-235B-A22B",
        "messages": [{"role": "user", "content": prompt}],
        "max_tokens": 8192,
        "temperature": 0.1,
        "response_format": {"type": "json_object"},
    }

    resp = httpx.post(
        f"{endpoint}/v1/chat/completions",
        json=payload,
        headers=headers,
        timeout=timeout,
    )
    resp.raise_for_status()

    content = resp.json()["choices"][0]["message"]["content"]
    return _parse_vlm_response(content)


# ── helpers ───────────────────────────────────────────────────────────────────

def _build_prompt(
    episodes_context: list[dict[str, Any]],
    target_market: str,
    max_characters: int,
) -> str:
    context_text = json.dumps(episodes_context[:5], ensure_ascii=False, indent=2)
    return f"""You are analyzing a Chinese short drama series for localization to {target_market}.

Given the following episode context (transcripts, scene descriptions, timecodes):
{context_text}

Extract and return a JSON object with exactly these keys:
{{
  "character_relationships": [
    {{"subject": "char_id", "relation": "description",
      "object": "char_id_or_entity", "evidence_timecodes": ["ep01:00:02:35"]}}
  ],
  "cultural_exposures": [
    {{"category": "currency|brand|institution|honorific|name|location|other",
      "description": "what was detected",
      "source_text": "original text",
      "timecodes": ["ep01:00:01:20"],
      "severity": "high|medium|low",
      "suggested_replacement": "target-market equivalent"}}
  ],
  "entities": [
    {{"type": "character|location|organization|amount|prop",
      "source_name": "original name",
      "localized_name": "target-market name",
      "context": "brief description",
      "first_appearance": "ep01:00:00:30"}}
  ],
  "plot_events": [
    {{"description": "event summary",
      "characters": ["char_id1"],
      "timecodes": ["ep01:00:03:00"],
      "episode_no": 1}}
  ]
}}

Return at most {max_characters} characters. All timecode strings must reference actual content.
Return ONLY the JSON object, no markdown fences."""


def _parse_vlm_response(text: str) -> dict[str, Any]:
    """Parse VLM JSON response, stripping markdown fences if present."""
    text = text.strip()
    if text.startswith("```"):
        lines = text.splitlines()
        text = "\n".join(lines[1:-1] if lines[-1].strip() == "```" else lines[1:])

    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        # Return empty structure rather than crashing the pipeline
        data = {}

    return {
        "character_relationships": data.get("character_relationships", []),
        "cultural_exposures": data.get("cultural_exposures", []),
        "entities": data.get("entities", []),
        "plot_events": data.get("plot_events", []),
    }
