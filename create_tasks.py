#!/usr/bin/env python3
"""
create_tasks.py — Creates Jira tasks in GC project for inactive projects.

For each row in inactive_projects.csv where:
  - Flag contains "🔴 Archive"
  - Lead Email is not empty
  - Jira Task is empty (task not yet created)

Creates a "Jira Project" issue in GC, then updates the CSV:
  - Jira Task  → issue key (e.g. GC-123)
  - Task URL   → link to issue
  - Flag       → "📋 Task Created"
"""

import os, sys, time, csv, datetime, logging
from pathlib import Path

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

import requests
from requests.auth import HTTPBasicAuth

# ── КОНФИГ ────────────────────────────────────────────────────
JIRA_URL       = "https://xsolla.atlassian.net"
JIRA_EMAIL     = os.environ.get("JIRA_EMAIL", "m.gordeeva@xsolla.com")
JIRA_API_TOKEN = os.environ.get("JIRA_API_TOKEN", "")
OUTPUT_DIR     = Path(os.environ.get("OUTPUT_DIR", "."))
DRY_RUN        = os.environ.get("DRY_RUN", "").lower() in ("1", "true", "yes")

GC_PROJECT_KEY    = "GC"
ISSUE_TYPE_ID     = "16716"   # "Jira Project" in GC
REPORTER_ACCOUNT  = "712020:2f19fee6-e1b5-4ff5-a7c1-d7be60eea03e"  # m.gordeeva@xsolla.com
DUE_DATE_DAYS     = 14        # today + 14 days

PROJECTS_CSV = OUTPUT_DIR / "inactive_projects.csv"

HEADERS = [
    "Project Key", "Project Name", "Project URL", "Issue Count",
    "Project Lead", "Lead Email", "Lead Status", "Last Updated", "Days Inactive",
    "First Seen Empty", "Empty Weeks", "Flag",
    "Jira Task", "Task URL", "Last Checked", "Flagged for Removal",
]

# ── ЛОГИРОВАНИЕ ───────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler("create_tasks.log", encoding="utf-8"),
    ],
)
log = logging.getLogger(__name__)

# ── JIRA API ──────────────────────────────────────────────────
_session = requests.Session()
_session.headers.update({"Accept": "application/json", "Content-Type": "application/json"})

def jira_request(method, path, retries=3, **kwargs):
    _session.auth = HTTPBasicAuth(JIRA_EMAIL, JIRA_API_TOKEN)
    url = f"{JIRA_URL}{path}"
    for attempt in range(retries):
        try:
            r = _session.request(method, url, timeout=30, **kwargs)
            if r.status_code == 429:
                wait = int(r.headers.get("Retry-After", 15))
                log.warning(f"Rate limit, ожидаю {wait}с...")
                time.sleep(wait)
                continue
            if r.status_code in (401, 403):
                log.error(f"Ошибка авторизации ({r.status_code}). Проверь JIRA_API_TOKEN.")
                sys.exit(1)
            r.raise_for_status()
            return r.json() if r.content else {}
        except requests.exceptions.HTTPError as e:
            log.warning(f"HTTP {e.response.status_code}: {e.response.text[:200]}")
            if attempt == retries - 1:
                raise
            time.sleep(3)
    return {}

_account_cache = {}

def get_account_id(email):
    """Ищет accountId пользователя по email."""
    if email in _account_cache:
        return _account_cache[email]
    try:
        data = jira_request("GET", "/rest/api/3/user/search", params={"query": email})
        for user in data:
            if user.get("emailAddress", "").lower() == email.lower():
                _account_cache[email] = user["accountId"]
                return user["accountId"]
    except Exception as e:
        log.warning(f"Не нашёл accountId для {email}: {e}")
    _account_cache[email] = None
    return None

def make_description(project_name, project_url):
    """Формирует description в формате ADF."""
    return {
        "type": "doc",
        "version": 1,
        "content": [
            {
                "type": "paragraph",
                "content": [{"type": "text", "text": "Hello,"}]
            },
            {
                "type": "paragraph",
                "content": [{"type": "text", "text": (
                    "As part of the Jira Integrity process, we are reviewing inactive projects "
                    "across Jira. The following project appears to be inactive "
                    "(no updates for over 4 months):"
                )}]
            },
            {
                "type": "bulletList",
                "content": [{
                    "type": "listItem",
                    "content": [{
                        "type": "paragraph",
                        "content": [{
                            "type": "text",
                            "text": project_name,
                            "marks": [{"type": "link", "attrs": {"href": project_url}}]
                        }]
                    }]
                }]
            },
            {
                "type": "paragraph",
                "content": [{"type": "text", "text": (
                    "Please let us know in the comments if this project can be archived."
                )}]
            },
            {
                "type": "paragraph",
                "content": [{"type": "text", "text": (
                    "If there are tasks that still need to be completed, feel free to transfer "
                    "them to an active project where the work will continue."
                )}]
            },
            {
                "type": "paragraph",
                "content": [
                    {"type": "text", "text": "If you have feedback on the Jira Integrity process, you can share it here: "},
                    {
                        "type": "text",
                        "text": "Submit feedback",
                        "marks": [{"type": "link", "attrs": {
                            "href": "https://xsolla.atlassian.net/jira/core/projects/QPM/form/4044"
                        }}]
                    }
                ]
            }
        ]
    }

def create_jira_task(row):
    """Создаёт задачу в GC. Возвращает (issue_key, issue_url) или (None, None)."""
    email      = row.get("Lead Email", "")
    project_key  = row["Project Key"]
    project_name = row["Project Name"]
    project_url  = row["Project URL"]

    assignee_id = get_account_id(email)
    if not assignee_id:
        log.warning(f"  {project_key}: не нашёл accountId для {email}, пропускаю")
        return None, None

    due_date = (datetime.date.today() + datetime.timedelta(days=DUE_DATE_DAYS)).isoformat()

    payload = {
        "fields": {
            "project":     {"key": GC_PROJECT_KEY},
            "issuetype":   {"id": ISSUE_TYPE_ID},
            "summary":     f"Jira Integrity: Review inactive project {project_key}",
            "description": make_description(project_name, project_url),
            "assignee":    {"accountId": assignee_id},
            "reporter":    {"accountId": REPORTER_ACCOUNT},
            "duedate":     due_date,
        }
    }

    if DRY_RUN:
        log.info(f"  [DRY RUN] {project_key} → задача была бы создана (assignee: {email}, due: {due_date})")
        return "DRY-RUN", f"{JIRA_URL}/browse/DRY-RUN"

    data = jira_request("POST", "/rest/api/3/issue", json=payload)
    key  = data.get("key")
    if not key:
        log.error(f"  {project_key}: не получили key из ответа: {data}")
        return None, None

    url = f"{JIRA_URL}/browse/{key}"
    log.info(f"  {project_key} → {key} ({url})")
    return key, url

# ── MAIN ─────────────────────────────────────────────────────
def main():
    log.info("=" * 60)
    log.info(f"Create GC Tasks — {datetime.date.today()}")
    if DRY_RUN:
        log.info("DRY RUN — задачи создаваться не будут")
    log.info("=" * 60)

    if not JIRA_API_TOKEN:
        log.error("JIRA_API_TOKEN не задан.")
        sys.exit(1)

    if not PROJECTS_CSV.exists():
        log.error(f"Файл не найден: {PROJECTS_CSV}")
        sys.exit(1)

    # Читаем CSV
    with open(PROJECTS_CSV, newline="", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    log.info(f"Загружено строк: {len(rows)}")

    # Добавляем недостающие колонки (на случай старого CSV)
    for row in rows:
        row.setdefault("Flagged for Removal", "")

    # Фильтруем кандидатов
    candidates = [
        r for r in rows
        if "🔴 Archive" in r.get("Flag", "")
        and r.get("Lead Email", "").strip()
        and not r.get("Jira Task", "").strip()
    ]
    log.info(f"Кандидатов для создания задач: {len(candidates)}")

    if not candidates:
        log.info("Нечего создавать.")
        return

    created = 0
    for row in candidates:
        log.info(f"Создаю задачу для {row['Project Key']} ({row['Project Name']})...")
        key, url = create_jira_task(row)
        if key:
            row["Jira Task"] = key
            row["Task URL"]  = url
            row["Flag"]      = "📋 Task Created"
            created += 1
        time.sleep(0.3)  # небольшая пауза между запросами

    log.info(f"\nСоздано задач: {created}")

    if DRY_RUN:
        log.info("[DRY RUN] CSV не обновлён")
        return

    # Перезаписываем CSV с обновлёнными данными
    fieldnames = HEADERS
    # Добавляем любые колонки из файла, которых нет в HEADERS
    extra = [k for k in rows[0].keys() if k not in fieldnames]
    fieldnames = fieldnames + extra

    with open(PROJECTS_CSV, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
        w.writeheader()
        w.writerows(rows)

    log.info(f"CSV обновлён: {PROJECTS_CSV}")
    log.info(f"\n{'='*60}\nГотово. Создано задач: {created}\n{'='*60}\n")

if __name__ == "__main__":
    main()
