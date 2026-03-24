# Inactive Jira Projects Detector

A Python script that automatically detects inactive Jira projects and outputs results to CSV files. Designed to run weekly via cron.

## What It Does

- Fetches all projects from Jira (764+ projects, fully paginated)
- Applies exclusion rules (archived, specific lead, category, name keywords)
- Checks each project's last issue activity via Jira REST API
- Flags projects with **no updates in 120+ days** for archiving
- Tracks **empty projects** (0 issues) week-over-week with escalating flags
- Preserves `First Seen Empty` and `Jira Task` data between runs
- Outputs two CSV files: current snapshot + full history

## Flags

| Flag | Condition |
|------|-----------|
| ⚪ Monitoring | Empty 1–2 weeks |
| 🟡 Watch | Empty 3–4 weeks |
| 🟠 At Risk | Empty 5–8 weeks |
| 🔴 Archive | Empty 9+ weeks, or inactive 120+ days |
| ⚠️ Lead Inactive | Project lead's account is deactivated |

## Output Columns

`Project Key` · `Project Name` · `Project URL` · `Issue Count` · `Project Lead` · `Lead Status` · `Last Updated` · `Days Inactive` · `First Seen Empty` · `Empty Weeks` · `Flag` · `Jira Task` · `Task URL` · `Last Checked`

## Setup

### 1. Install dependencies

```bash
pip install -r requirements.txt
```

### 2. Configure credentials

Create a `.env` file in the project folder:

```env
JIRA_EMAIL=you@yourcompany.com
JIRA_API_TOKEN=your_jira_api_token_here
```

Get your Jira API token at: https://id.atlassian.com/manage-profile/security/api-tokens

### 3. Run

```bash
python3 detect_inactive.py
```

Results are saved to:
- `inactive_projects.csv` — current snapshot (overwritten each run)
- `inactive_projects_history.csv` — cumulative history (append-only)

## Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `JIRA_EMAIL` | `""` | Jira account email |
| `JIRA_API_TOKEN` | `""` | Jira API token (required) |
| `OUTPUT_DIR` | `.` | Directory for CSV output |
| `DRY_RUN` | `0` | Set to `1` to skip writing files |
| `TEST_LIMIT` | `0` | Limit to N projects (for testing) |

## Weekly Automation (cron)

Run every Monday at 9:00 AM:

```bash
crontab -e
```

Add:

```
0 9 * * 1 cd /Users/yourname/inactive-jira-projects && python3 detect_inactive.py >> run.log 2>&1
```

## Exclusion Rules

Edit these constants at the top of `detect_inactive.py`:

```python
INACTIVE_DAYS     = 120                        # days without updates → flagged
EXCLUDED_KEYWORDS = ["run", "change", "jump"]  # skip projects with these words in name
EXCLUDED_LEAD     = "Shurick Agapitov"         # skip projects with this lead
EXCLUDED_CATEGORY = "project_discovery"        # skip projects in this category
```

## Why Not n8n?

n8n was the original approach but was abandoned due to:

- **Pagination never worked** — HTTP node couldn't loop through all 764 projects; always returned only the first 100
- **Jira removed `/rest/api/3/search`** — the endpoint n8n relied on for issue counts no longer exists; the replacement uses cursor-based pagination with no `total` field, which n8n can't handle natively
- **0-item output kills the chain** — when a node returns 0 rows, all downstream nodes stop; workarounds made the workflow fragile and hard to debug
- **Silent failures** — wrong counts and missing projects are nearly impossible to catch and fix in a no-code environment

Python gives full control over pagination, error handling, and data logic.
