# VTV Budget Overrun Runbook

## Overview

This runbook describes what happens when a project reaches its compute/spend hard limit, how the system responds automatically, and the steps operators and users can take to resolve the situation.

---

## Budget Limit Types

| Limit Type   | Behavior at Threshold                        |
|--------------|----------------------------------------------|
| `soft_limit` | Warning alert fired; project continues       |
| `hard_limit` | Dispatch suspended; project enters OVER_BUDGET|

Limits are set per-project in the `project_budgets` table and via the API:
```bash
GET /v1/projects/{project_id}/budget
# Returns: { "soft_limit_usd": 80.00, "hard_limit_usd": 100.00, "spent_usd": 97.43 }
```

---

## Automatic System Behavior at Hard Limit

When `spent_usd >= hard_limit_usd`:

1. Orchestrator sets project status to `OVER_BUDGET`.
2. All PENDING stages for the project are cancelled immediately.
3. RUNNING stages are allowed to finish (they have already incurred cost).
4. No new stages can be dispatched until budget is resolved.
5. A `budget.hard_limit_exceeded` event is emitted and an alert fires to #vtv-oncall.
6. The project owner receives an email/webhook notification.

**Verify current state:**
```bash
GET /v1/projects/{project_id}
# Check: { "status": "OVER_BUDGET", "budget": { "spent_usd": 100.21, "hard_limit_usd": 100.00 } }
```

```sql
SELECT id, status, budget_spent_usd, budget_hard_limit_usd
FROM projects
WHERE id = '<project_id>';
```

---

## Operator Actions

### Option A: Increase the Hard Limit

If the overage is expected (e.g., project scope expanded), raise the limit:

```bash
PATCH /v1/projects/{project_id}/budget
{
  "hard_limit_usd": 150.00,
  "reason": "Approved scope increase — ticket VTV-4821"
}
# Requires admin scope
```

After the limit is raised, the project status automatically returns to `ACTIVE` and dispatch resumes.

### Option B: Reset Budget Counter (New Billing Period)

At the start of a new billing cycle, reset the spend counter:

```bash
POST /v1/projects/{project_id}/budget:reset
{
  "period_start": "2026-08-01",
  "reason": "Monthly reset"
}
```

### Option C: Suspend Project (Intentional Halt)

If the overrun is unexpected and under investigation, keep the project suspended:

```bash
POST /v1/projects/{project_id}:suspend
{ "reason": "Budget overrun under review" }
```

This holds the OVER_BUDGET state even if the limit is raised, until an operator explicitly resumes:

```bash
POST /v1/projects/{project_id}:resume
```

---

## Diagnosing Unexpected Overruns

### Find the high-cost stages

```sql
SELECT stage_type, model_version,
       COUNT(*) as count,
       SUM(cost_usd) as total_cost_usd,
       AVG(cost_usd) as avg_cost_usd
FROM stages
WHERE project_id = '<project_id>'
  AND created_at > NOW() - INTERVAL '24 hours'
GROUP BY stage_type, model_version
ORDER BY total_cost_usd DESC;
```

### Check for runaway retry loops

```sql
SELECT stage_id, COUNT(*) as attempt_count, SUM(cost_usd) as total_cost
FROM stage_attempts
WHERE project_id = '<project_id>'
GROUP BY stage_id
HAVING COUNT(*) > 3
ORDER BY total_cost DESC;
```

### Check cost by episode

```bash
GET /v1/projects/{project_id}/episodes?include_cost=true
# Sort by cost_usd descending
```

---

## Preventing Future Overruns

### Set soft limit alerts

Ensure every project has a soft limit at 80% of hard limit:

```bash
PATCH /v1/projects/{project_id}/budget
{
  "soft_limit_usd": 80.00,
  "hard_limit_usd": 100.00
}
```

### Configure budget alert webhooks

```bash
POST /v1/projects/{project_id}/alerts
{
  "type": "budget_soft_limit",
  "channel": "slack",
  "target": "#project-alerts"
}
```

### Review cost anomaly alerts

The system fires `budget.anomaly` when hourly spend exceeds 2x the 7-day hourly average. Ensure this alert is routed to the project owner.

---

## Refund / Credit Policy

If the overrun was caused by a platform bug (e.g., runaway retries due to orchestrator defect):

1. Document the affected stage IDs and total erroneous cost.
2. File a credit request: `POST /v1/admin/billing/credits` with `project_id`, `amount_usd`, and `reason`.
3. Credits are applied to the next billing period automatically.

---

## Escalation

- Unexpected overrun > $50: page #vtv-oncall immediately.
- Suspected billing system bug: escalate to platform-billing team.
- Customer dispute: loop in account management within 24 hours.

---

## Reference: Budget Event Log

```sql
SELECT event_type, amount_usd, created_at, actor, notes
FROM budget_events
WHERE project_id = '<project_id>'
ORDER BY created_at DESC
LIMIT 20;
```
