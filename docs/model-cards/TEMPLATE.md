# Model Card: <MODEL_SLUG>

<!-- Copy this file to docs/model-cards/<slug>.md and fill in all fields. -->

## Identity

| Field | Value |
|---|---|
| Slug | `<slug>` |
| Full name | |
| Adapter | `asr` / `vision` / `segmentation` / `visual_generation` / `tts` / `lipsync` |
| Version / commit | |
| Official source | |
| License | |
| Status | `RESEARCH` / `SANDBOX` / `BENCHMARK` / `CANDIDATE` / `APPROVED` / `SUPERSEDED` |
| Promoted date | |
| Superseded by | _(if SUPERSEDED)_ |

---

## Capabilities

- Primary task:
- Supported languages / resolutions / durations:
- Known limitations:

---

## Hardware Requirements

| GPU | VRAM (batch 1) | VRAM (target batch) | Cold-start p95 |
|---|---|---|---|
| A10G | | | |
| A100-40G | | | |
| A100-80G | | | |

---

## Reproducibility

| Field | Value |
|---|---|
| Weight hash (SHA-256 or HF commit SHA) | |
| CUDA version | |
| cuDNN version | |
| PyTorch version | |
| Modal image digest | |
| Inference command | `modal run modal_stubs/<slug>.py::run` |

Dependencies snapshot: `docs/model-cards/<slug>-deps.txt`

---

## Benchmark Results

Benchmark date:
GPU class used:
Golden Shot set: `golden_shots/<adapter>/`

| Metric | This model | Baseline | Delta |
|---|---|---|---|
| Primary quality metric | | | |
| Cost per 1 000 units (USD) | | | |
| Latency mean (s) | | | |
| Latency p95 (s) | | | |
| Cold-start p95 (s) | | | |
| Stability failure rate | | | |

Full benchmark JSON: `docs/model-cards/<slug>-benchmark.json`

---

## Repro Gate

- [ ] Independent reproduction completed by: _(engineer name, date)_
- [ ] Delta within 5 % threshold: yes / no

---

## Canary Record

| Field | Value |
|---|---|
| Canary start date | |
| Canary traffic weight | |
| Canary end date | |
| Alert triggers during canary | none / _(describe)_ |

---

## Promotion Notes

_(Any deviations, caveats, or special routing rules for the production router.)_

---

## Change Log

| Date | Engineer | Change |
|---|---|---|
| | | Initial research |
