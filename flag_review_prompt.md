# Prompt: Jira Integrity — Flagged for Removal Review

## Context

You are reviewing Jira tasks created in the **Garbage Collection (GC) project** on a specific run date as part of the monthly Jira Integrity process.

Each task (issue type: `Jira Project`) was automatically created for an inactive Jira project — either no issue updates for 120+ days, or 0 issues total. The assigned person is the project lead. They were asked to confirm whether the project can be archived.

## Your Job

For each GC task from the current run (issue type = `Jira Project`, created = `{RUN_DATE}`), set the `Flagged for removal` field (`customfield_19311`) based on the rules below.

## Rules

### Set `Flagged for removal = Yes` if the comment indicates the project should be archived:
- "can be archived", "please archive", "no longer needed", "close it", "go ahead", "yes", "archive", "not needed", "safe to archive", "feel free to archive"

### Set `Flagged for removal = No` if the comment indicates the project should stay active:
- "leave it", "keep it", "still active", "we're using it", "do not archive", "please leave", "active state", "in use", "don't close", "working on it"

### Set `Flagged for removal = No` if (no comment case):
- The issue status is **Done/Closed** AND there is no comment AND the flag is not set
- Reasoning: the assignee closed the task without leaving feedback — treat as "they want to keep the project"

### Leave blank if:
- No comment, flag not set, and issue is still **open** — still waiting for a response from the lead

## Ambiguous Comments

If the comment is unclear or doesn't directly address archiving (e.g. "ok", "noted", "thanks"), leave the flag blank and flag it for manual review.

## Scope — Only Process Tasks Matching ALL of These

- **Project:** `GC`
- **Issue type:** `Jira Project`
- **Created:** `{RUN_DATE}` (e.g. `2026-03-24` for the March run)
- **Do NOT** touch tasks from earlier runs, other issue types, or other projects

## Field Values

| Decision | Field value | Option ID |
|----------|-------------|-----------|
| Yes — archive | `Yes` | `25050` |
| No — keep active | `No` | `25051` |

## Example (March 24, 2026 run)

| Issue | Comment | Flag set |
|-------|---------|----------|
| GC-729 | "Please leave it as is in active state" | `No` |
| GC-700 | "Can be archived" | `Yes` |
| GC-715 | *(no comment, status: Done)* | `No` |
| GC-720 | *(no comment, status: Open)* | *(leave blank)* |
