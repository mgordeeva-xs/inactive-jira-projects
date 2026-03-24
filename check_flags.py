#!/usr/bin/env python3
"""
check_flags.py — Checks "Flagged for removal" field on GC tasks.

For each row in inactive_projects.csv where Task URL is set,
reads customfield_19311 (Flagged for removal) from Jira and
writes Yes / No / (empty) into the "Flagged for Removal" column.
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

PROJECTS_CSV           = OUTPUT_DIR / "inactive_projects.csv"
FLAGGED_FIELD          = "customfield_19311"

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
        logging.FileHandler("check_flags.log", encoding="utf-8"),
    ],
)
log = logging.getLogger(__name__)

# ── JIRA API ──────────────────────────────────────────────────
_session = requests.Session()
_session.headers.update({"Accept": "application/json"})

def jira_get(path, params=None, retries=3):
    _session.auth = HTTPBasicAuth(JIRA_EMAIL, JIRA_API_TOKEN)
    url = f"{JIRA_URL}{path}"
    for attempt in range(retries):
        try:
            r = _session.get(url, params=params, timeout=30)
            if r.status_code == 429:
                wait = int(r.headers.get("Retry-After", 15))
                log.warning(f"Rate limit, ожидаю {wait}с...")
                time.sleep(wait)
                continue
            if r.status_code in (401, 403):
                log.error(f"Ошибка авторизации ({r.status_code}).")
                sys.exit(1)
            if r.status_code == 404:
                return None  # задача удалена или недоступна
            r.raise_for_status()
            return r.json()
        except requests.exceptions.HTTPError as e:
            log.warning(f"HTTP {e.response.status_code}, попытка {attempt+1}/{retries}")
            if attempt == retries - 1:
                return None
            time.sleep(3)
    return None

def get_flag_value(issue_key):
    """Возвращает значение Flagged for removal: 'Yes', 'No' или ''."""
    data = jira_get(f"/rest/api/3/issue/{issue_key}", params={"fields": FLAGGED_FIELD})
    if not data:
        return ""
    field = (data.get("fields") or {}).get(FLAGGED_FIELD)
    if not field:
        return ""
    return field.get("value", "")

# ── MAIN ─────────────────────────────────────────────────────
def main():
    log.info("=" * 60)
    log.info(f"Check Flagged for Removal — {datetime.date.today()}")
    log.info("=" * 60)

    if not JIRA_API_TOKEN:
        log.error("JIRA_API_TOKEN не задан.")
        sys.exit(1)

    if not PROJECTS_CSV.exists():
        log.error(f"Файл не найден: {PROJECTS_CSV}")
        sys.exit(1)

    with open(PROJECTS_CSV, newline="", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    log.info(f"Загружено строк: {len(rows)}")

    # Добавляем недостающие колонки
    for row in rows:
        row.setdefault("Flagged for Removal", "")

    targets = [r for r in rows if r.get("Jira Task", "").strip()]
    log.info(f"Задач для проверки: {len(targets)}")

    if not targets:
        log.info("Нет задач для проверки.")
        return

    updated = 0
    for row in targets:
        issue_key = row["Jira Task"].strip()
        log.info(f"  Проверяю {issue_key} ({row['Project Key']})...")
        value = get_flag_value(issue_key)
        if row.get("Flagged for Removal") != value:
            row["Flagged for Removal"] = value
            updated += 1
        time.sleep(0.2)

    log.info(f"\nОбновлено строк: {updated}")

    # Перезаписываем CSV
    fieldnames = HEADERS
    extra = [k for k in rows[0].keys() if k not in fieldnames]
    fieldnames = fieldnames + extra

    with open(PROJECTS_CSV, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
        w.writeheader()
        w.writerows(rows)

    log.info(f"CSV обновлён: {PROJECTS_CSV}")
    log.info(f"\n{'='*60}\nГотово. Обновлено: {updated}\n{'='*60}\n")

if __name__ == "__main__":
    main()
