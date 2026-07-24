# VTV Fault Recovery Runbook

## Overview

This runbook covers common failure modes in the VTV short-drama production pipeline and the steps to diagnose and recover from each.

---

## Stage Failure Recovery

### Symptom: Stage stuck in RUNNING past lease expiry

**Cause:** Worker crashed without updating stage status, or network partition prevented heartbeat.

**Detection:**
```sql
SELECT id, project_id, stage_type, status, lease_expires_at
FROM stages
WHERE status = 'RUNNING' AND lease_expires_at < NOW();
```

**Action:**
1. Scheduler auto-reclaims via lease expiry (runs every 60s). No manual action needed in most cases.
2. If auto-reclaim is not firing, check scheduler health:
   ```bash
   curl http://localhost:8000/health
   # or
   kubectl logs -l app=vtv-orchestrator --tail=50
   ```
3. Manual retry:
   ```bash
   POST /v1/projects/{project_id}/stages/{stage_id}:retry
   ```
4. Confirm stage transitions to PENDING then RUNNING again.

---

### Symptom: Object write succeeded but DB commit failed

**Cause:** Storage write completed but the database transaction rolled back (e.g., connection loss mid-commit).

**Detection:** Stage status is FAILED. Check orphan asset table:
```sql
SELECT * FROM orphan_assets WHERE stage_id = '<stage_id>';
```

**Action:**
1. Stage is already in FAILED state — no manual DB cleanup needed.
2. Orphan asset is registered automatically.
3. Re-run the stage; the idempotency key prevents duplicate asset adoption:
   ```bash
   POST /v1/projects/{project_id}/stages/{stage_id}:retry
   ```
4. Verify asset adoption succeeds and orphan record is cleared.

---

## Modal Worker Crash / OOM

### Symptom: Worker exits unexpectedly or runs out of memory

**Cause:** Model inference OOM, unhandled exception in worker code, Modal container eviction.

**Detection:**
- Stage transitions to FAILED with `error_code: WORKER_CRASH` or `WORKER_OOM`.
- Check Modal dashboard for container exit codes.

**Action:**
1. Modal auto-retries up to `max_retries=2`. Wait for automatic retry cycle.
2. If all retries fail, stage moves to FAILED permanently.
3. For OOM: consider reducing batch size or upgrading GPU tier in Modal config.
4. Manual retry after fixing root cause:
   ```bash
   POST /v1/projects/{project_id}/stages/{stage_id}:retry
   ```
5. If systematic OOM on a model version, consider circuit-breaking — see MODEL_CIRCUIT_BREAK.md.

---

## DB Connection Loss

### Symptom: Orchestrator cannot reach PostgreSQL

**Cause:** DB server restart, network issue, connection pool exhaustion.

**Detection:**
```bash
grep "connection refused\|pool timeout\|could not connect" /var/log/vtv-orchestrator.log
```

**Action:**
1. Orchestrator uses a connection pool with automatic retry (exponential backoff, up to 30s).
2. In-flight stage dispatches are paused; queued work is not lost.
3. If DB recovers, orchestrator resumes automatically.
4. If orchestrator is stuck, restart it:
   ```bash
   systemctl restart vtv-orchestrator
   # or
   kubectl rollout restart deployment/vtv-orchestrator
   ```
5. Verify DB connectivity:
   ```bash
   psql $DATABASE_URL -c "SELECT 1;"
   ```

---

## MinIO / S3 Unavailable

### Symptom: Object storage returns errors; stage dispatch paused

**Cause:** MinIO container down, S3 endpoint unreachable, credential rotation.

**Detection:**
```bash
curl -I http://<minio-host>:9000/minio/health/live
# or check S3:
aws s3 ls s3://<bucket> --region <region>
```

**Action:**
1. Orchestrator detects storage errors and pauses new stage dispatch automatically.
2. Stages already RUNNING continue until their lease expires.
3. Restore storage:
   - MinIO: `docker restart minio` or redeploy container.
   - S3: verify IAM credentials and bucket policy.
4. After storage is restored, resume dispatch:
   ```bash
   POST /v1/admin/dispatch:resume
   ```
5. Retry any stages that failed during the outage window.

---

## General Escalation

- Check orchestrator logs first: `kubectl logs -l app=vtv-orchestrator`
- Check Modal worker logs in Modal dashboard.
- Slack: #vtv-oncall for escalation.
- All stage state transitions are logged to the `stage_events` table for audit.
