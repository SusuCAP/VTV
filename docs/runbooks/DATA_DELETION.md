# VTV Data Deletion & Retention Runbook

## Overview

This runbook covers project deletion, asset cleanup, and data retention policies for the VTV pipeline. All deletion operations are soft-delete by default with a 30-day grace period before hard deletion.

---

## Project Deletion

### Soft Delete (Default)

Marks the project deleted; data is retained for 30 days before purge.

```bash
DELETE /v1/projects/{project_id}
# Response: { "status": "SOFT_DELETED", "purge_after": "2026-08-23T00:00:00Z" }
```

**What happens:**
- Project status set to `DELETED` in DB.
- No new jobs can be submitted.
- Running stages are allowed to finish; new dispatch is blocked.
- Assets remain in object storage until hard-delete.
- Project is excluded from list/search results.

**Undo within grace period:**
```bash
POST /v1/projects/{project_id}:restore
```

---

### Hard Delete (Immediate, Irreversible)

Use only when legally required (GDPR/CCPA right-to-erasure) or for test data cleanup.

```bash
DELETE /v1/projects/{project_id}?hard=true
# Requires admin scope token
```

**Steps executed (in order):**
1. Cancel all PENDING and RUNNING stages (force-fail with reason `PROJECT_DELETED`).
2. Delete all assets from object storage (MinIO/S3).
3. Delete all stage records, job records, and episode records.
4. Delete project row from DB.
5. Emit `project.hard_deleted` audit event.

**Verify deletion:**
```sql
SELECT COUNT(*) FROM projects WHERE id = '<project_id>';
-- Should return 0
SELECT COUNT(*) FROM stages WHERE project_id = '<project_id>';
-- Should return 0
```

---

## Asset Retention Policy

| Asset Type        | Retention Period | Storage Class      |
|-------------------|------------------|--------------------|
| Raw uploads       | 90 days          | Standard           |
| Stage outputs     | 90 days          | Standard           |
| Final renders     | 1 year           | Standard-IA        |
| QC snapshots      | 30 days          | Standard           |
| Logs / metadata   | 1 year           | Glacier / Archive  |

### Automated Purge

A nightly cron job runs asset expiry:
```bash
# Check purge job status
SELECT * FROM cron_jobs WHERE name = 'asset_purge' ORDER BY run_at DESC LIMIT 5;
```

To manually trigger purge of expired assets:
```bash
POST /v1/admin/assets:purge-expired
# Returns count of assets scheduled for deletion
```

---

## Episode Deletion

Deleting an episode deletes all its stages and associated assets.

```bash
DELETE /v1/projects/{project_id}/episodes/{episode_id}
```

**Cascade:**
- All stages for the episode → CANCELLED or FAILED.
- Stage output objects deleted from storage.
- Episode row removed from DB.

---

## User Data (PII) Removal

If a GDPR/CCPA erasure request is received:

1. Identify all projects owned by the user:
   ```sql
   SELECT id FROM projects WHERE owner_id = '<user_id>';
   ```
2. Hard-delete each project (see above).
3. Remove user record:
   ```bash
   DELETE /v1/admin/users/{user_id}?erase=true
   ```
4. Confirm audit log entry written to `compliance_events` table.
5. Respond to requestor within 30 days per regulatory requirement.

---

## Orphan Asset Cleanup

Orphan assets arise when storage writes succeed but DB commits fail. Cleanup:

```bash
# List orphan assets older than 24 hours
GET /v1/admin/orphan-assets?older_than=24h

# Purge them
POST /v1/admin/orphan-assets:purge
```

```sql
-- Manual check
SELECT * FROM orphan_assets WHERE created_at < NOW() - INTERVAL '24 hours';
```

---

## Audit Trail

All deletion events are written to the `audit_log` table and are immutable:
```sql
SELECT * FROM audit_log
WHERE event_type LIKE '%deleted%'
  AND created_at > NOW() - INTERVAL '7 days'
ORDER BY created_at DESC;
```

Audit logs are retained for 7 years regardless of project deletion.
