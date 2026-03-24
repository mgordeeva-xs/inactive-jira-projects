#!/usr/bin/env python3
"""
Inactive Jira Projects Detection — v3
"""

import os, sys, time, datetime, logging, csv
from pathlib import Path

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

import requests
from requests.auth import HTTPBasicAuth

# ── КОНФИГ ────────────────────────────────────────────────────
JIRA_URL         = "https://xsolla.atlassian.net"
JIRA_EMAIL       = os.environ.get("JIRA_EMAIL", "m.gordeeva@xsolla.com")
JIRA_API_TOKEN   = os.environ.get("JIRA_API_TOKEN", "")
OUTPUT_DIR = Path(os.environ.get("OUTPUT_DIR", "."))

INACTIVE_DAYS     = 120
EXCLUDED_KEYWORDS = ["run", "change", "jump"]
EXCLUDED_LEAD     = "Shurick Agapitov"
EXCLUDED_CATEGORY = "project_discovery"
DRY_RUN           = os.environ.get("DRY_RUN", "").lower() in ("1", "true", "yes")
# Для тестирования: TEST_LIMIT=20 запустит только первые 20 проектов
TEST_LIMIT        = int(os.environ.get("TEST_LIMIT", "0"))

HEADERS = [
    "Project Key", "Project Name", "Project URL", "Issue Count",
    "Project Lead", "Lead Status", "Last Updated", "Days Inactive",
    "First Seen Empty", "Empty Weeks", "Flag",
    "Jira Task", "Task URL", "Last Checked",
]

# ── ЛОГИРОВАНИЕ ───────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler("inactive_projects.log", encoding="utf-8"),
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
                log.warning(f"Jira rate limit, ожидаю {wait}с...")
                time.sleep(wait)
                continue
            if r.status_code in (401, 403):
                log.error(f"Ошибка авторизации Jira ({r.status_code}). Проверь JIRA_API_TOKEN.")
                sys.exit(1)
            r.raise_for_status()
            return r.json()
        except requests.exceptions.Timeout:
            log.warning(f"Timeout, попытка {attempt+1}/{retries}")
            if attempt == retries - 1: raise
            time.sleep(3)
        except requests.exceptions.HTTPError as e:
            log.warning(f"HTTP {e.response.status_code}, попытка {attempt+1}/{retries}")
            if attempt == retries - 1: raise
            time.sleep(3)
    return {}

def get_all_projects():
    log.info("Загружаю все проекты из Jira...")
    projects, start_at = [], 0
    while True:
        data  = jira_get("/rest/api/3/project/search", params={
            "maxResults": 100, "startAt": start_at,
            "action": "browse", "expand": "lead,projectCategory",
        })
        batch = data.get("values", [])
        projects.extend(batch)
        total = data.get("total", len(projects))
        log.info(f"  Загружено {len(projects)}/{total}...")
        if data.get("isLast", True) or not batch:
            break
        start_at += len(batch)
    log.info(f"Всего проектов: {len(projects)}")
    return projects

def filter_projects(projects):
    result  = []
    skipped = {"archived": 0, "category": 0, "lead": 0, "keyword": 0}
    for p in projects:
        name        = p.get("name", "")
        lead        = p.get("lead") or {}
        lead_name   = lead.get("displayName", "")
        category    = (p.get("projectCategory") or {}).get("name", "")
        lead_active = lead.get("active", True)
        if p.get("archived"):                                   skipped["archived"] += 1; continue
        if category.lower() == EXCLUDED_CATEGORY:               skipped["category"] += 1; continue
        if lead_name == EXCLUDED_LEAD:                          skipped["lead"]     += 1; continue
        if any(kw in name.lower() for kw in EXCLUDED_KEYWORDS): skipped["keyword"]  += 1; continue
        result.append({
            "projectKey": p["key"], "projectName": p["name"],
            "projectUrl": f"{JIRA_URL}/projects/{p['key']}",
            "projectLead": lead_name, "leadActive": lead_active,
        })
    log.info(f"После исключений: {len(result)} (пропущено: {skipped})")
    return result

def get_issue_info(project_key):
    """
    Возвращает (issue_count_str, last_updated_iso | None).

    Jira удалила /rest/api/3/search (с полем total).
    /rest/api/3/search/jql использует курсорную пагинацию без total.
    Поэтому:
      - Нет issues → count = 0, last_updated = None
      - Есть issues, isLast=True, issues=[1 item] → count = 1
      - Есть issues, isLast=False → count = ">1" (точный недоступен)
    """
    try:
        data = jira_get("/rest/api/3/search/jql", params={
            "jql":        f'project="{project_key}" ORDER BY updated DESC',
            "maxResults": 1,
            "fields":     "updated",
        })
        issues       = data.get("issues", [])
        is_last      = data.get("isLast", True)
        last_updated = issues[0]["fields"]["updated"] if issues else None

        if not issues:
            issue_count = 0
        elif is_last:
            issue_count = 1          # ровно 1 issue
        else:
            issue_count = ">1"       # точное число недоступно через API

        return issue_count, last_updated
    except Exception as e:
        log.warning(f"  Ошибка для {project_key}: {e}")
        return 0, None

# ── CSV ───────────────────────────────────────────────────────
PROJECTS_CSV = OUTPUT_DIR / "inactive_projects.csv"
HISTORY_CSV  = OUTPUT_DIR / "inactive_projects_history.csv"

def read_existing_csv():
    """Читаем текущий CSV чтобы сохранить First Seen Empty и Jira Task между запусками."""
    if not PROJECTS_CSV.exists():
        return {}
    with open(PROJECTS_CSV, newline="", encoding="utf-8") as f:
        return {r["Project Key"]: r for r in csv.DictReader(f) if r.get("Project Key")}

def write_projects_csv(report):
    """Полная перезапись projects CSV."""
    with open(PROJECTS_CSV, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=HEADERS)
        w.writeheader()
        w.writerows(report)
    log.info(f"Projects: {len(report)} строк → {PROJECTS_CSV}")

def append_history_csv(report):
    """Дописываем в history CSV (создаём с заголовком если нет)."""
    new_file = not HISTORY_CSV.exists()
    with open(HISTORY_CSV, "a", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=HEADERS)
        if new_file:
            w.writeheader()
        w.writerows(report)
    log.info(f"History: +{len(report)} строк → {HISTORY_CSV}")

# ── БИЗНЕС-ЛОГИКА ────────────────────────────────────────────
def calc_flag(empty_weeks):
    if empty_weeks <= 2:   return f"⚪ Monitoring ({empty_weeks}w empty)"
    elif empty_weeks <= 4: return f"🟡 Watch ({empty_weeks}w empty)"
    elif empty_weeks <= 8: return f"🟠 At Risk ({empty_weeks}w empty)"
    else:                  return f"🔴 Archive ({empty_weeks}w empty)"

def build_report(projects_data, existing):
    today     = datetime.date.today()
    today_str = today.isoformat()
    report    = []

    for p in projects_data:
        key          = p["projectKey"]
        issue_count  = p["issueCount"]
        last_updated = p["lastUpdated"]
        lead_active  = p["leadActive"]
        prev         = existing.get(key)
        lead_status  = "✅ Active" if lead_active else "⚠️ Inactive"

        if not last_updated:
            # Проект без issues
            if prev and prev.get("First Seen Empty"):
                first_seen = str(prev["First Seen Empty"])
                try:
                    first_date  = datetime.date.fromisoformat(first_seen)
                    weeks_since = (today - first_date).days // 7
                    empty_weeks = max(weeks_since, 1)
                except (ValueError, TypeError):
                    log.warning(f"Не смог прочитать First Seen Empty для {key}: '{first_seen}'")
                    first_seen  = today_str
                    empty_weeks = 1
            else:
                first_seen  = today_str
                empty_weeks = 1

            last_updated_display = f"No issues (last checked: {today_str})"
            days_inactive        = ""
            flag                 = calc_flag(empty_weeks)

        else:
            # Проект с issues
            try:
                last_date = datetime.date.fromisoformat(last_updated[:10])
            except (ValueError, TypeError):
                log.warning(f"Не смог распарсить дату для {key}: '{last_updated}'")
                continue

            diff_days = (today - last_date).days
            if diff_days < INACTIVE_DAYS:
                continue   # Активный — пропускаем, уйдёт из таблицы при overwrite

            last_updated_display = last_date.isoformat()
            days_inactive        = diff_days
            first_seen           = ""
            empty_weeks          = 0
            flag                 = "🔴 Archive"

        if not lead_active:
            flag += " | ⚠️ Lead Inactive"

        report.append({
            "Project Key":      key,
            "Project Name":     p["projectName"],
            "Project URL":      p["projectUrl"],
            "Issue Count":      issue_count,
            "Project Lead":     p["projectLead"],
            "Lead Status":      lead_status,
            "Last Updated":     last_updated_display,
            "Days Inactive":    days_inactive,
            "First Seen Empty": first_seen,
            "Empty Weeks":      empty_weeks,
            "Flag":             flag,
            "Jira Task":        (prev or {}).get("Jira Task", ""),
            "Task URL":         (prev or {}).get("Task URL", ""),
            "Last Checked":     today_str,
        })

    log.info(f"Неактивных проектов: {len(report)}")
    return report

# ── MAIN ─────────────────────────────────────────────────────
def main():
    log.info("=" * 60)
    log.info(f"Inactive Jira Projects Detection — {datetime.date.today()}")
    if DRY_RUN:   log.info("DRY RUN — в таблицу ничего не записывается")
    if TEST_LIMIT: log.info(f"TEST MODE — только первые {TEST_LIMIT} проектов")
    log.info("=" * 60)

    if not JIRA_API_TOKEN:
        log.error("JIRA_API_TOKEN не задан.")
        sys.exit(1)

    # 1. Проекты
    log.info("\n[1/4] Получаю проекты Jira...")
    all_projects      = get_all_projects()
    filtered_projects = filter_projects(all_projects)
    if TEST_LIMIT:
        filtered_projects = filtered_projects[:TEST_LIMIT]
    if not filtered_projects:
        log.warning("Нет проектов после фильтрации.")
        return

    # 2. Issues
    log.info(f"\n[2/4] Запрашиваю issues ({len(filtered_projects)} проектов)...")
    projects_data = []
    for i, proj in enumerate(filtered_projects, 1):
        if i % 100 == 0:
            log.info(f"  {i}/{len(filtered_projects)}...")
        count, last_updated = get_issue_info(proj["projectKey"])
        projects_data.append({**proj, "issueCount": count, "lastUpdated": last_updated})
    log.info("Issues получены")

    # 3. Читаем существующий CSV (для сохранения First Seen Empty и Jira Task)
    log.info("\n[3/4] Читаю существующие данные...")
    existing = read_existing_csv()
    log.info(f"  Текущих строк в CSV: {len(existing)}")

    # 4. Строим репорт
    log.info("\n[4/4] Строю репорт и записываю...")
    report = build_report(projects_data, existing)

    if DRY_RUN:
        log.info(f"\n[DRY RUN] Будет записано {len(report)} строк:")
        for row in report[:30]:
            log.info(
                f"  {row['Project Key']:<10} | issues={str(row['Issue Count']):<4} | "
                f"{row['Flag']:<35} | {row['Last Updated'][:30]}"
            )
        if len(report) > 30:
            log.info(f"  ... и ещё {len(report)-30} строк")
        return

    write_projects_csv(report)
    if report:
        append_history_csv(report)

    log.info(f"\n{'='*60}\nГотово. Неактивных проектов: {len(report)}\n{'='*60}\n")

if __name__ == "__main__":
    main()
