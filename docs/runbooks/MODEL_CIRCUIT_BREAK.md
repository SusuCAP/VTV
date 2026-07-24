# VTV Model Circuit Breaker Runbook

## Overview

This runbook covers how to circuit-break a bad model release in the VTV pipeline — stopping it from processing new jobs while preserving in-flight work and enabling rollback to the last known-good version.

---

## When to Circuit-Break

Trigger a circuit break when a model release exhibits any of the following:

- Output quality score drops below threshold (QC failure rate > 10% over 30 min window)
- Worker OOM rate spikes (> 3 consecutive OOMs on different jobs)
- Inference latency p99 > 3x baseline
- Output artifacts are corrupt or empty
- Security / content policy violation detected in outputs

---

## Step 1: Identify the Bad Model

Check the active canary or production model version:

```bash
GET /v1/admin/models/active
# Returns: { "model_id": "vtv-lipsync-v2.3.1", "stage": "canary", "traffic_pct": 20 }
```

Check recent QC failure rate:
```bash
GET /v1/admin/models/{model_id}/metrics?window=30m
# Look for: qc_failure_rate, oom_count, p99_latency_ms
```

Query DB directly:
```sql
SELECT model_version, COUNT(*) as total,
       SUM(CASE WHEN status = 'FAILED' THEN 1 ELSE 0 END) as failures
FROM stages
WHERE created_at > NOW() - INTERVAL '30 minutes'
GROUP BY model_version;
```

---

## Step 2: Circuit-Break the Model

### Option A: Pause canary traffic (canary stage only)

Sets canary traffic to 0% without removing the canary entry. Safest option.

```bash
POST /v1/admin/models/{model_id}:pause-canary
# Response: { "traffic_pct": 0, "status": "PAUSED" }
```

### Option B: Hard circuit-break (production model)

Stops all new dispatch to this model version immediately.

```bash
POST /v1/admin/models/{model_id}:circuit-break
# Requires admin scope
# Response: { "status": "CIRCUIT_BROKEN", "broken_at": "2026-07-24T03:33:45Z" }
```

**Effect:**
- New stages will not be dispatched to this model version.
- Stages already RUNNING continue to completion (their lease expires normally).
- Orchestrator falls back to the previous stable model version automatically.

---

## Step 3: Verify Fallback is Active

```bash
GET /v1/admin/models/active
# Should now show previous stable version with 100% traffic
```

```sql
-- Confirm new stages are using the fallback model
SELECT model_version, COUNT(*) FROM stages
WHERE status = 'PENDING' OR (status = 'RUNNING' AND created_at > NOW() - INTERVAL '5 minutes')
GROUP BY model_version;
```

---

## Step 4: Drain In-Flight Jobs (Optional)

If the bad model is causing data corruption, drain its in-flight stages:

```bash
POST /v1/admin/models/{model_id}:drain
# Cancels all PENDING stages for this model; RUNNING stages finish their lease
```

Confirm drain:
```sql
SELECT COUNT(*) FROM stages
WHERE model_version = '<model_id>' AND status IN ('PENDING', 'RUNNING');
-- Should reach 0 within lease_duration seconds
```

---

## Step 5: Rollback Model Version

Once circuit-broken, roll back to the previous stable release:

```bash
POST /v1/admin/models:rollback
{
  "target_version": "vtv-lipsync-v2.2.9",
  "reason": "v2.3.1 qc_failure_rate > 15%"
}
```

This promotes the target version back to production with 100% traffic.

---

## Step 6: Re-run Failed Jobs

After rollback is confirmed active, retry stages that failed under the bad model:

```bash
# List failed stages from the bad model window
GET /v1/admin/stages?model_version={model_id}&status=FAILED&since=<broken_at>

# Bulk retry
POST /v1/admin/stages:bulk-retry
{ "model_version": "<model_id>", "status": "FAILED", "since": "<broken_at>" }
```

---

## Step 7: Post-Incident

1. Write a brief incident note in the `model_incidents` table:
   ```bash
   POST /v1/admin/model-incidents
   { "model_id": "<model_id>", "summary": "...", "root_cause": "..." }
   ```
2. File a bug on the model team's tracker.
3. Do not re-promote the broken version without a fixed build and QC sign-off.
4. Update canary promotion thresholds if the circuit break was due to a threshold miss.

---

## Alert Thresholds Reference

| Metric                  | Warning    | Circuit-Break Trigger |
|-------------------------|------------|-----------------------|
| QC failure rate (30m)   | > 5%       | > 10%                 |
| Worker OOM count        | 2          | 3 consecutive         |
| p99 latency             | > 2x base  | > 3x base             |
| Empty output rate       | > 1%       | > 3%                  |
