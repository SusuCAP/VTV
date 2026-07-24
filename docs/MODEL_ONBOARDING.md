# Model Onboarding Checklist

Reference: VTV v3.2 §21.5

This document defines the process for evaluating and promoting a new AI model into production.
Every model (ASR, Vision, Segmentation, Visual Generation, TTS, Lipsync) must pass all six
steps before it may be referenced by the production router.

---

## Step 1: Research

Gather authoritative information before writing a single line of inference code.

### Checklist

- [ ] Identify the official source (HuggingFace model card, paper, vendor docs)
- [ ] Document capability scope and known limitations (languages, resolutions, durations)
- [ ] Record weight status: open weights / gated / proprietary / hosted-API
- [ ] Measure VRAM requirements at inference batch size 1 and target batch size
- [ ] Note CUDA/driver/Python version constraints from the official release
- [ ] Check for existing community benchmarks relevant to short-drama production
- [ ] Confirm license is compatible with commercial production use

### Commands

```bash
# Pull model card metadata from HuggingFace
pip install huggingface_hub
python - <<'EOF'
from huggingface_hub import model_info
info = model_info("<org>/<model>")
print(info.cardData)
print("License:", info.cardData.get("license"))
print("Tags:", info.tags)
EOF

# Estimate VRAM with a dry-run (no data, just model load)
python - <<'EOF'
import torch
# Replace with actual model class
model = <ModelClass>.from_pretrained("<org>/<model>")
model.eval()
allocated = torch.cuda.memory_allocated() / 1e9
reserved  = torch.cuda.memory_reserved()  / 1e9
print(f"Allocated: {allocated:.2f} GB  Reserved: {reserved:.2f} GB")
EOF
```

### Acceptance Criteria

- Model card created at `docs/model-cards/<slug>.md` using `docs/model-cards/TEMPLATE.md`
- VRAM figure confirmed on target GPU class (A10G / A100-40G / A100-80G)
- License recorded and approved by project lead

---

## Step 2: Sandbox

Validate that the model runs at all inside an isolated Modal environment before touching
shared infrastructure.

### Checklist

- [ ] Create a throwaway Modal stub (`modal_stubs/sandbox_<slug>.py`) — do not touch existing stubs
- [ ] Install only the model's own dependencies; record the exact pip freeze output
- [ ] Run the minimal inference path (one sample input, verify output shape/type)
- [ ] Confirm no dependency conflicts with the existing VTV environment
- [ ] Delete or archive the sandbox stub after this step passes

### Commands

```bash
# Create and deploy isolated Modal sandbox environment
modal run modal_stubs/sandbox_<slug>.py::run_sandbox

# Capture dependency snapshot
modal run modal_stubs/sandbox_<slug>.py::freeze_deps | tee docs/model-cards/<slug>-deps.txt

# Verify output shape
modal run modal_stubs/sandbox_<slug>.py::smoke_test
```

### Acceptance Criteria

- Smoke test completes without error
- Dependency list recorded in the model card
- No unresolvable conflicts with `pyproject.toml` base environment

---

## Step 3: Benchmark

Measure quality, cost, and reliability on fixed infrastructure before integration.

### Checklist

- [ ] Pin GPU class and Modal image version for reproducibility
- [ ] Assemble Golden Shot set: 20 representative inputs covering edge cases
- [ ] Run each Golden Shot 3 times; record mean and stddev of primary quality metric
- [ ] Record wall-clock latency per sample and estimated cost per 1 000 units
- [ ] Measure cold-start time (first invocation after idle period)
- [ ] Run 50-call stability test; record failure/timeout rate
- [ ] Compare against the current APPROVED baseline on the same Golden Shot set

### Commands

```bash
# Run benchmark suite (fixed seed, fixed GPU)
uv run python scripts/benchmark_model.py \
    --adapter <adapter_name> \
    --model <slug> \
    --shots golden_shots/<adapter_name>/ \
    --repeats 3 \
    --output docs/model-cards/<slug>-benchmark.json

# Cold-start measurement
uv run python scripts/measure_cold_start.py --model <slug> --trials 5

# Stability run
uv run python scripts/stability_run.py --model <slug> --calls 50
```

### Acceptance Criteria

- Primary quality metric >= current baseline (or within agreed regression budget)
- Cost per 1 000 units documented
- Cold-start p95 <= 30 s (A10G) / 45 s (A100)
- Stability run failure rate <= 2 %

---

## Step 4: Repro Gate

Ensure the benchmark result is fully reproducible by a different engineer on a different day.

### Checklist

- [ ] Commit the inference adapter code to a feature branch
- [ ] Record exact weight hash (SHA-256 of each checkpoint file or HuggingFace commit SHA)
- [ ] Record CUDA version, cuDNN version, PyTorch version, and Modal image digest
- [ ] Record the exact `modal run` command used in the benchmark
- [ ] A second engineer runs the benchmark independently and confirms results match within 5 %
- [ ] All of the above recorded in the model card

### Commands

```bash
# Generate weight hash
python - <<'EOF'
import hashlib, sys
path = sys.argv[1]
sha = hashlib.sha256(open(path,"rb").read()).hexdigest()
print(sha)
EOF /path/to/weights.safetensors

# HuggingFace commit SHA (pinned download)
huggingface-cli download <org>/<model> --revision <commit_sha>

# Capture runtime environment
modal run modal_stubs/<slug>.py::print_env_info
```

### Acceptance Criteria

- Independent reproduction delta <= 5 % on all primary metrics
- Exact weight hash committed to model card
- CUDA/PyTorch/Modal image version triple recorded
- Feature branch passes CI (`uv run pytest tests/unit -q`)

---

## Step 5: Candidate

Roll out to 1-5 % of production traffic while keeping the previous APPROVED release hot.

### Checklist

- [ ] Merge feature branch after Repro Gate sign-off
- [ ] Set adapter canary weight to 1-5 % in `configs/environments/prod.yaml`
- [ ] Ensure previous APPROVED model is still the default (weight >= 95 %)
- [ ] Monitor production metrics dashboard for 24 h minimum
- [ ] Alert thresholds: quality regression > 3 %, error rate > 1 %, p95 latency > 2x baseline
- [ ] Escalation path defined: who to page and rollback command documented

### Commands

```bash
# Set canary weight (example for ASR adapter)
# Edit configs/environments/prod.yaml:
#   asr_adapter_mode: local_models
#   asr_canary_model: <slug>
#   asr_canary_weight: 0.03   # 3 %

# Deploy updated config
uv run python scripts/deploy_config.py --env prod

# Monitor canary metrics
uv run python scripts/canary_monitor.py --adapter <adapter_name> --model <slug> --watch

# Rollback if needed
uv run python scripts/canary_rollback.py --adapter <adapter_name>
```

### Acceptance Criteria

- 24 h canary window with no alert triggers
- Quality metric within 2 % of baseline across canary traffic
- Rollback tested (dry run) before canary goes live

---

## Step 6: Approved

Promote the model to the default; router may now select it automatically.

### Checklist

- [ ] All Step 5 acceptance criteria met
- [ ] Update `configs/environments/prod.yaml`: set model as default, remove canary weight
- [ ] Update model card status to `APPROVED` with promotion date
- [ ] Archive previous model card status as `SUPERSEDED` (do not delete)
- [ ] Tag the Git commit: `model/<adapter>/<slug>/approved`
- [ ] Announce in team channel with benchmark summary

### Commands

```bash
# Promote to default
# Edit configs/environments/prod.yaml — remove canary fields, set adapter to <slug>

# Deploy
uv run python scripts/deploy_config.py --env prod

# Tag
git tag model/<adapter>/<slug>/approved
git push origin model/<adapter>/<slug>/approved

# Verify production traffic is routing to new model
uv run python scripts/traffic_check.py --adapter <adapter_name> --expected <slug>
```

### Acceptance Criteria

- 100 % of production traffic routes to new model
- No increase in error rate or quality regression in first 2 h post-promotion
- Model card updated and commit tagged
- Previous model's Modal image retained for at least 30 days (rollback window)
