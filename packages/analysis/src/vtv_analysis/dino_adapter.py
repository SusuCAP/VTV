"""DINOv3 visual embedding adapter (P12-B).

Provides frame-level visual embeddings for costume / scene consistency retrieval.
Implements a simple ``VisualEmbeddingAdapter`` that is used by the QC pipeline
to compare candidate frames against the Anchor Pack reference images.

All heavy imports are lazy so the class can be imported in CI without GPU.

Env vars:
    VTV_DINO_MODEL_ID   – HuggingFace model ID (default: facebook/dinov2-large)
    VTV_DINO_DEVICE     – cuda (default) | cpu
    VTV_DINO_BATCH_SIZE – frames per forward pass (default: 8)
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import numpy as np
from pathlib import Path


@dataclass(frozen=True, slots=True)
class DINOv3Adapter:
    """DINOv3 (DINOv2-large) visual embedding adapter.

    Usage:
        adapter = DINOv3Adapter()
        emb = adapter.embed_image(Path("frame.jpg"))          # np.ndarray (1024,)
        sim = adapter.similarity(emb_a, emb_b)               # float in [0, 1]
        matches = adapter.retrieve(query_emb, gallery, top_k=5)  # list[int]
    """

    _release: str = field(default="dinov3@1")

    @property
    def model_release(self) -> str:  # noqa: D102
        return self._release

    # ── public API ────────────────────────────────────────────────────────────

    def embed_image(self, image_path: Path) -> np.ndarray:  # type: ignore[name-defined]
        """Return a L2-normalised embedding for a single image file."""
        import numpy as np
        import torch
        from PIL import Image

        model_id = os.environ.get("VTV_DINO_MODEL_ID", "facebook/dinov2-large")
        device = os.environ.get("VTV_DINO_DEVICE", "cuda" if torch.cuda.is_available() else "cpu")

        processor, model = _load_dino(model_id, device)

        image = Image.open(image_path).convert("RGB")
        inputs = processor(images=image, return_tensors="pt").to(device)

        with torch.no_grad():
            outputs = model(**inputs)
            emb = outputs.last_hidden_state[:, 0, :].squeeze(0).cpu().numpy()

        # L2 normalise
        norm = np.linalg.norm(emb)
        return emb / max(norm, 1e-8)

    def embed_video_frame(
        self,
        video_path: Path,
        timestamp_seconds: float,
        output_dir: Path,
    ) -> np.ndarray:  # type: ignore[name-defined]
        """Extract a single frame at *timestamp_seconds* and embed it."""
        import subprocess
        import tempfile

        output_dir.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(suffix=".jpg", dir=output_dir, delete=False) as tmp:
            frame_path = Path(tmp.name)

        subprocess.run(
            [
                "ffmpeg", "-y", "-ss", str(timestamp_seconds),
                "-i", str(video_path),
                "-vframes", "1", str(frame_path),
            ],
            check=True,
            capture_output=True,
        )
        return self.embed_image(frame_path)

    def similarity(self, emb_a: np.ndarray, emb_b: np.ndarray) -> float:  # type: ignore[name-defined]
        """Cosine similarity between two L2-normalised embeddings."""
        import numpy as np
        return float(np.dot(emb_a, emb_b))

    def retrieve(
        self,
        query: np.ndarray,  # type: ignore[name-defined]
        gallery: list[np.ndarray],  # type: ignore[name-defined]
        top_k: int = 5,
    ) -> list[int]:
        """Return indices of the *top_k* most similar embeddings in *gallery*."""
        import numpy as np
        if not gallery:
            return []
        scores = [self.similarity(query, g) for g in gallery]
        sorted_indices = np.argsort(scores)[::-1]
        return [int(i) for i in sorted_indices[:top_k]]

    def consistency_score(
        self,
        reference_embeddings: list[np.ndarray],  # type: ignore[name-defined]
        candidate_embedding: np.ndarray,  # type: ignore[name-defined]
    ) -> float:
        """Mean cosine similarity of *candidate* against all *reference_embeddings*.

        Used by the visual QC pipeline to check costume / scene consistency:
        a score below 0.7 indicates a significant visual deviation.
        """
        if not reference_embeddings:
            return 1.0
        return sum(self.similarity(candidate_embedding, r) for r in reference_embeddings) / len(
            reference_embeddings
        )


# ── helpers ──────────────────────────────────────────────────────────────────

_dino_cache: dict[str, tuple] = {}


def _load_dino(model_id: str, device: str):
    """Load DINOv2 processor and model (cached per model_id)."""
    key = f"{model_id}:{device}"
    if key not in _dino_cache:
        from transformers import AutoImageProcessor, AutoModel  # type: ignore[import]
        processor = AutoImageProcessor.from_pretrained(model_id)
        model = AutoModel.from_pretrained(model_id).to(device).eval()
        _dino_cache[key] = (processor, model)
    return _dino_cache[key]
