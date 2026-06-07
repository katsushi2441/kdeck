from __future__ import annotations

import datetime as dt
import json
import os
import sqlite3
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any

from dotenv import load_dotenv


ROOT = Path(__file__).resolve().parents[1]
load_dotenv(ROOT / ".env")

DATA_DIR = Path(os.environ.get("KDECK_DATA_DIR", ROOT / "storage")).expanduser()
DB_PATH = Path(os.environ.get("KDECK_CONTROLLER_DB", DATA_DIR / "controller.sqlite")).expanduser()
RQDB4AI_API_URL = os.environ.get("KDECK_RQDB4AI_API_URL", os.environ.get("RQDB4AI_API_URL", "http://127.0.0.1:18300")).rstrip("/")
RQDB4AI_API_TOKEN = os.environ.get("KDECK_RQDB4AI_API_TOKEN", os.environ.get("RQDB4AI_API_TOKEN", "")).strip()
WORKER_STATUS_URL = os.environ.get("KDECK_WORKER_STATUS_URL", "https://aixec.exbridge.jp/api.php?path=worker/status")
CONTROLLER_ENABLED = os.environ.get("KDECK_CONTROLLER_ENABLED", "1").strip().lower() not in {"0", "false", "no", "off"}
TICK_SECONDS = int(os.environ.get("KDECK_CONTROLLER_TICK_SECONDS", "30"))
DEFAULT_COOLDOWN_SECONDS = int(os.environ.get("KDECK_CONTROLLER_COOLDOWN_SECONDS", "900"))


MARKET_TASKS = [
    {
        "label": "高単価AI PC・ゲーミング",
        "group": "ai_pc_gaming",
        "genre_id": "",
        "keywords": ["ゲーミングPC", "ミニPC", "GPU", "AI PC", "ワークステーション"],
        "exclude_keywords": ["中古", "ジャンク"],
        "target_count": 500,
        "description_policy": "高単価でAmazon/Rakuten双方の購買につながりやすい商品を優先する",
        "reason": "kdeck goal queue default market-pipeline task",
    },
    {
        "label": "高単価ガジェット・家電",
        "group": "premium_gadget",
        "genre_id": "",
        "keywords": ["ロボット掃除機", "ポータブル電源", "4Kモニター", "NAS", "ドローン"],
        "exclude_keywords": ["中古", "ジャンク"],
        "target_count": 500,
        "description_policy": "単価が高く、AI/効率化文脈で紹介しやすい商品を優先する",
        "reason": "kdeck goal queue retry market-pipeline task",
    },
    {
        "label": "ビジネス効率化・オフィス機器",
        "group": "office_productivity",
        "genre_id": "",
        "keywords": ["デスクチェア", "昇降デスク", "プロジェクター", "プリンター", "シュレッダー"],
        "exclude_keywords": ["中古", "ジャンク"],
        "target_count": 500,
        "description_policy": "経営者・個人事業主が購入検討しやすい高単価商品を優先する",
        "reason": "kdeck goal queue retry market-pipeline task",
    },
]


DEFAULT_GOALS = [
    {
        "goal_name": "aixec-market-pipeline",
        "worker_name": "aixec-market-pipeline-enqueue",
        "description": "AIxEC market-pipeline 新規500件 x 1日4回 = 2000件",
        "function_name": "aixec_market_jobs.market_pipeline_job",
        "queue": "auto",
        "resource": "ollama:192.168.0.14:gemma4:e4b",
        "daily_target": 2000,
        "per_run_target": 500,
        "max_runs_per_day": 4,
        "cooldown_seconds": DEFAULT_COOLDOWN_SECONDS,
        "priority": 10,
        "enabled": 1,
        "payload": {
            "kwargs": {
                "dry_run": False,
                "source": "worker_auto",
                "resource": "ollama",
                "ollama_host": "192.168.0.14",
                "ollama_model": "gemma4:e4b",
                "limit": 500,
                "hits": 20,
                "pages": 3,
                "max_candidates": 800,
                "score_mode": "heuristic",
                "skip_sns": False,
            },
            "meta": {
                "project": "aixec",
                "app": "market_pipeline",
                "source": "worker_auto",
                "resource": "ollama",
                "ollama_host": "192.168.0.14",
                "ollama_model": "gemma4:e4b",
                "worker_name": "aixec-market-pipeline-enqueue",
            },
            "timeout": 3600,
            "result_ttl": 86400,
            "failure_ttl": 604800,
        },
    },
    {
        "goal_name": "aixec-growth-agent",
        "worker_name": "aixec-growth-agent-enqueue",
        "description": "AIxEC growth-agent を目標達成型で実行",
        "function_name": "aixec_market_jobs.growth_agent_job",
        "queue": "auto",
        "resource": "aixec-api",
        "daily_target": 1,
        "per_run_target": 1,
        "max_runs_per_day": 2,
        "cooldown_seconds": 1800,
        "priority": 20,
        "enabled": 1,
        "payload": {
            "kwargs": {
                "dry_run": False,
                "source": "worker_auto",
                "market_limit": 20,
                "skip_claude": False,
            },
            "meta": {
                "project": "aixec",
                "app": "growth_agent",
                "source": "worker_auto",
                "worker_name": "aixec-growth-agent-enqueue",
            },
            "timeout": 1800,
            "result_ttl": 86400,
            "failure_ttl": 604800,
        },
    },
]


def utc_now() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat()


def today_key() -> str:
    return dt.datetime.now(dt.timezone(dt.timedelta(hours=9))).date().isoformat()


def connect() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH, timeout=30)
    conn.row_factory = sqlite3.Row
    return conn


def init_db() -> None:
    with connect() as conn:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS goals (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                goal_name TEXT NOT NULL UNIQUE,
                worker_name TEXT NOT NULL,
                description TEXT NOT NULL DEFAULT '',
                function_name TEXT NOT NULL,
                queue TEXT NOT NULL DEFAULT 'auto',
                resource TEXT NOT NULL DEFAULT '',
                daily_target INTEGER NOT NULL DEFAULT 1,
                per_run_target INTEGER NOT NULL DEFAULT 1,
                max_runs_per_day INTEGER NOT NULL DEFAULT 1,
                cooldown_seconds INTEGER NOT NULL DEFAULT 900,
                priority INTEGER NOT NULL DEFAULT 100,
                enabled INTEGER NOT NULL DEFAULT 1,
                status TEXT NOT NULL DEFAULT 'waiting',
                current_job_id TEXT NOT NULL DEFAULT '',
                last_result TEXT NOT NULL DEFAULT '{}',
                last_note TEXT NOT NULL DEFAULT '',
                cooldown_until TEXT NOT NULL DEFAULT '',
                payload TEXT NOT NULL DEFAULT '{}',
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS goal_runs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                goal_id INTEGER NOT NULL,
                day TEXT NOT NULL,
                job_id TEXT NOT NULL DEFAULT '',
                rq_status TEXT NOT NULL DEFAULT '',
                business_status TEXT NOT NULL DEFAULT '',
                items INTEGER NOT NULL DEFAULT 0,
                ok INTEGER NOT NULL DEFAULT 0,
                note TEXT NOT NULL DEFAULT '',
                result TEXT NOT NULL DEFAULT '{}',
                started_at TEXT NOT NULL,
                finished_at TEXT NOT NULL DEFAULT ''
            );
            CREATE TABLE IF NOT EXISTS controller_events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                level TEXT NOT NULL,
                message TEXT NOT NULL,
                data TEXT NOT NULL DEFAULT '{}',
                created_at TEXT NOT NULL
            );
            """
        )
        now = utc_now()
        for goal in DEFAULT_GOALS:
            conn.execute(
                """
                INSERT INTO goals (
                    goal_name, worker_name, description, function_name, queue, resource,
                    daily_target, per_run_target, max_runs_per_day, cooldown_seconds,
                    priority, enabled, payload, created_at, updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(goal_name) DO NOTHING
                """,
                (
                    goal["goal_name"],
                    goal["worker_name"],
                    goal["description"],
                    goal["function_name"],
                    goal["queue"],
                    goal["resource"],
                    goal["daily_target"],
                    goal["per_run_target"],
                    goal["max_runs_per_day"],
                    goal["cooldown_seconds"],
                    goal["priority"],
                    goal["enabled"],
                    json.dumps(goal["payload"], ensure_ascii=False),
                    now,
                    now,
                ),
            )


def row_dict(row: sqlite3.Row | None) -> dict[str, Any]:
    if row is None:
        return {}
    data = dict(row)
    for key in ("payload", "last_result", "result", "data"):
        if key in data:
            try:
                data[key] = json.loads(data[key] or "{}")
            except json.JSONDecodeError:
                data[key] = {}
    return data


def event(level: str, message: str, data: dict[str, Any] | None = None) -> None:
    with connect() as conn:
        insert_event(conn, level, message, data)


def insert_event(conn: sqlite3.Connection, level: str, message: str, data: dict[str, Any] | None = None) -> None:
    conn.execute(
        "INSERT INTO controller_events(level, message, data, created_at) VALUES (?, ?, ?, ?)",
        (level, message, json.dumps(data or {}, ensure_ascii=False), utc_now()),
    )


def api_request(method: str, base: str, path: str, payload: dict[str, Any] | None = None, token: str = "", timeout: int = 20) -> dict[str, Any]:
    body = None
    headers = {"Accept": "application/json", "User-Agent": "kdeck-controller/0.1"}
    if payload is not None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        headers["Content-Type"] = "application/json; charset=utf-8"
    if token:
        headers["Authorization"] = "Bearer " + token
    req = urllib.request.Request(base.rstrip("/") + path, data=body, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as res:
            raw = res.read().decode("utf-8", errors="replace")
            status_code = getattr(res, "status", 0)
    except urllib.error.HTTPError as exc:
        raw = exc.read().decode("utf-8", errors="replace")
        return {"ok": False, "status_code": exc.code, "error": raw[:1000]}
    except OSError as exc:
        return {"ok": False, "status_code": 0, "error": str(exc)}
    try:
        data = json.loads(raw) if raw else {}
    except json.JSONDecodeError:
        data = {"raw": raw}
    if isinstance(data, dict):
        data.setdefault("status_code", status_code)
        return data
    return {"ok": True, "status_code": status_code, "data": data}


def rq_get(path: str, timeout: int = 20) -> dict[str, Any]:
    return api_request("GET", RQDB4AI_API_URL, path, token=RQDB4AI_API_TOKEN, timeout=timeout)


def rq_post(path: str, payload: dict[str, Any], timeout: int = 20) -> dict[str, Any]:
    return api_request("POST", RQDB4AI_API_URL, path, payload, token=RQDB4AI_API_TOKEN, timeout=timeout)


def worker_status() -> dict[str, Any]:
    url = urllib.parse.urlparse(WORKER_STATUS_URL)
    base = f"{url.scheme}://{url.netloc}"
    path = url.path + (("?" + url.query) if url.query else "")
    return api_request("GET", base, path, timeout=12)


def daily_totals(conn: sqlite3.Connection, goal_id: int, day: str) -> dict[str, int]:
    row = conn.execute(
        """
        SELECT COUNT(*) AS runs, COALESCE(SUM(items), 0) AS items
        FROM goal_runs
        WHERE goal_id = ? AND day = ? AND finished_at != ''
        """,
        (goal_id, day),
    ).fetchone()
    return {"runs": int(row["runs"] or 0), "items": int(row["items"] or 0)}


def extract_result(job: dict[str, Any]) -> dict[str, Any]:
    result = job.get("result")
    if isinstance(result, dict):
        return result
    preview = job.get("preview") or {}
    output = preview.get("output_preview")
    if isinstance(output, str) and output.startswith("{"):
        try:
            parsed = json.loads(output)
            if isinstance(parsed, dict):
                return parsed
        except json.JSONDecodeError:
            pass
    return {}


def job_items(job: dict[str, Any], result: dict[str, Any]) -> int:
    for source in (result, result.get("metrics") if isinstance(result.get("metrics"), dict) else {}, job.get("lifecycle") or {}):
        if not isinstance(source, dict):
            continue
        for key in ("items", "created", "registered", "selected"):
            value = source.get(key)
            try:
                return int(value or 0)
            except (TypeError, ValueError):
                continue
    return 0


def evaluate_job(job: dict[str, Any], goal: dict[str, Any]) -> dict[str, Any]:
    rq_status = str(job.get("status") or "")
    lifecycle = job.get("lifecycle") if isinstance(job.get("lifecycle"), dict) else {}
    result = extract_result(job)
    result_status = str(result.get("status") or lifecycle.get("state") or rq_status).lower()
    items = job_items(job, result)
    terminal = bool(lifecycle.get("terminal", rq_status in {"finished", "failed", "stopped", "canceled"}))
    note = str(result.get("note") or lifecycle.get("note") or "")
    if rq_status in {"queued", "started", "deferred", "scheduled"} or not terminal:
        return {"terminal": False, "ok": False, "status": rq_status or "running", "items": items, "note": note, "result": result}
    if rq_status in {"failed", "stopped", "canceled"} or result_status in {"failed", "error", "down"}:
        return {"terminal": True, "ok": False, "status": result_status or rq_status, "items": items, "note": note, "result": result}
    per_target = int(goal.get("per_run_target") or 1)
    if items >= per_target:
        return {"terminal": True, "ok": True, "status": "ok", "items": items, "note": note, "result": result}
    return {
        "terminal": True,
        "ok": False,
        "status": "under_target",
        "items": items,
        "note": note or f"items {items} < target {per_target}",
        "result": result,
    }


def market_task_for_attempt(attempt: int) -> dict[str, Any]:
    task = dict(MARKET_TASKS[attempt % len(MARKET_TASKS)])
    task["target_count"] = 500
    task["reason"] = f"{task.get('reason', '')}; attempt={attempt + 1}"
    return task


def enqueue_goal(conn: sqlite3.Connection, goal: dict[str, Any]) -> dict[str, Any]:
    payload = dict(goal.get("payload") or {})
    kwargs = dict(payload.get("kwargs") or {})
    meta = dict(payload.get("meta") or {})
    today = today_key()
    run_count = conn.execute(
        "SELECT COUNT(*) AS c FROM goal_runs WHERE goal_id = ? AND day = ?",
        (goal["id"], today),
    ).fetchone()["c"]
    if goal["goal_name"] == "aixec-market-pipeline":
        kwargs["task"] = market_task_for_attempt(int(run_count or 0))
        kwargs["target_count"] = int(goal.get("per_run_target") or 500)
        kwargs["limit"] = int(goal.get("per_run_target") or 500)
    request = {
        "queue": goal.get("queue") or "auto",
        "function": goal["function_name"],
        "kwargs": kwargs,
        "meta": meta,
        "timeout": int(payload.get("timeout") or 1800),
        "result_ttl": int(payload.get("result_ttl") or 86400),
        "failure_ttl": int(payload.get("failure_ttl") or 604800),
    }
    response = rq_post("/api/enqueue", request, timeout=30)
    if not response.get("ok"):
        raise RuntimeError(f"RQDB4AI enqueue failed: {response}")
    job = response.get("job") if isinstance(response.get("job"), dict) else {}
    job_id = str(job.get("id") or "")
    now = utc_now()
    conn.execute(
        "INSERT INTO goal_runs(goal_id, day, job_id, rq_status, business_status, started_at, result) VALUES (?, ?, ?, ?, ?, ?, ?)",
        (goal["id"], today, job_id, str(job.get("status") or "queued"), "running", now, json.dumps(response, ensure_ascii=False)),
    )
    conn.execute(
        "UPDATE goals SET status = 'running', current_job_id = ?, last_note = ?, updated_at = ? WHERE id = ?",
        (job_id, "RQDB4AIへ投入しました", now, goal["id"]),
    )
    insert_event(conn, "info", f"enqueued {goal['goal_name']}", {"job_id": job_id, "request": request, "response": response})
    return response


def refresh_running_goal(conn: sqlite3.Connection, goal: dict[str, Any]) -> bool:
    job_id = str(goal.get("current_job_id") or "")
    if not job_id:
        conn.execute("UPDATE goals SET status = 'waiting', updated_at = ? WHERE id = ?", (utc_now(), goal["id"]))
        return True
    detail = rq_get("/api/jobs/" + urllib.parse.quote(job_id), timeout=20)
    if not detail.get("ok"):
        conn.execute(
            "UPDATE goals SET status = 'hold', last_note = ?, updated_at = ? WHERE id = ?",
            (f"RQDB4AI job detail unavailable: {detail.get('error') or detail}", utc_now(), goal["id"]),
        )
        return True
    job = detail.get("job") if isinstance(detail.get("job"), dict) else {}
    evaluation = evaluate_job(job, goal)
    if not evaluation["terminal"]:
        conn.execute(
            "UPDATE goals SET last_result = ?, last_note = ?, updated_at = ? WHERE id = ?",
            (json.dumps(detail, ensure_ascii=False), evaluation["note"], utc_now(), goal["id"]),
        )
        return False
    now = utc_now()
    conn.execute(
        """
        UPDATE goal_runs
        SET rq_status = ?, business_status = ?, items = ?, ok = ?, note = ?, result = ?, finished_at = ?
        WHERE job_id = ?
        """,
        (
            str(job.get("status") or ""),
            str(evaluation["status"]),
            int(evaluation["items"] or 0),
            1 if evaluation["ok"] else 0,
            str(evaluation["note"] or ""),
            json.dumps(detail, ensure_ascii=False),
            now,
            job_id,
        ),
    )
    totals = daily_totals(conn, int(goal["id"]), today_key())
    if totals["items"] >= int(goal.get("daily_target") or 1):
        status = "complete_today"
        note = f"daily target complete: {totals['items']}/{goal['daily_target']}"
        cooldown_until = ""
    elif totals["runs"] >= int(goal.get("max_runs_per_day") or 1):
        status = "complete_today"
        note = f"max runs reached: runs={totals['runs']} items={totals['items']}/{goal['daily_target']}"
        cooldown_until = ""
    elif evaluation["ok"]:
        status = "cooldown"
        cooldown_until = (dt.datetime.now(dt.timezone.utc) + dt.timedelta(seconds=int(goal.get("cooldown_seconds") or DEFAULT_COOLDOWN_SECONDS))).isoformat()
        note = f"run ok: +{evaluation['items']} items, today {totals['items']}/{goal['daily_target']}"
    else:
        status = "cooldown"
        cooldown_until = (dt.datetime.now(dt.timezone.utc) + dt.timedelta(seconds=max(600, int(goal.get("cooldown_seconds") or DEFAULT_COOLDOWN_SECONDS)))).isoformat()
        note = f"under target or failed: +{evaluation['items']} items, retry after cooldown"
    conn.execute(
        """
        UPDATE goals
        SET status = ?, current_job_id = '', last_result = ?, last_note = ?, cooldown_until = ?, updated_at = ?
        WHERE id = ?
        """,
        (status, json.dumps(detail, ensure_ascii=False), note, cooldown_until, now, goal["id"]),
    )
    insert_event(conn, "info" if evaluation["ok"] else "warn", f"finished {goal['goal_name']}", {"job_id": job_id, "evaluation": evaluation, "totals": totals})
    return True


def cooldown_ready(goal: dict[str, Any]) -> bool:
    value = str(goal.get("cooldown_until") or "")
    if not value:
        return True
    try:
        until = dt.datetime.fromisoformat(value)
    except ValueError:
        return True
    return dt.datetime.now(dt.timezone.utc) >= until


def tick() -> dict[str, Any]:
    init_db()
    if not CONTROLLER_ENABLED:
        return {"ok": True, "enabled": False, "action": "disabled"}
    if not RQDB4AI_API_TOKEN:
        event("error", "RQDB4AI token is not configured", {})
        return {"ok": False, "enabled": True, "error": "RQDB4AI token is not configured"}
    with connect() as conn:
        running = conn.execute("SELECT * FROM goals WHERE enabled = 1 AND status = 'running' ORDER BY priority, id LIMIT 1").fetchone()
        if running is not None:
            changed = refresh_running_goal(conn, row_dict(running))
            return {"ok": True, "action": "refresh_running", "changed": changed}
        day = today_key()
        for row in conn.execute("SELECT * FROM goals WHERE enabled = 1 ORDER BY priority, id").fetchall():
            goal = row_dict(row)
            totals = daily_totals(conn, int(goal["id"]), day)
            if totals["items"] >= int(goal["daily_target"] or 1) or totals["runs"] >= int(goal["max_runs_per_day"] or 1):
                conn.execute(
                    "UPDATE goals SET status = 'complete_today', last_note = ?, updated_at = ? WHERE id = ?",
                    (f"today {totals['items']}/{goal['daily_target']} runs={totals['runs']}/{goal['max_runs_per_day']}", utc_now(), goal["id"]),
                )
                continue
            if str(goal.get("status")) == "hold":
                return {"ok": True, "action": "blocked_by_hold", "goal_name": goal["goal_name"], "note": goal.get("last_note") or ""}
            if not cooldown_ready(goal):
                conn.execute("UPDATE goals SET status = 'cooldown', updated_at = ? WHERE id = ?", (utc_now(), goal["id"]))
                return {"ok": True, "action": "cooldown", "goal_name": goal["goal_name"], "cooldown_until": goal.get("cooldown_until") or ""}
            return {"ok": True, "action": "enqueue", "response": enqueue_goal(conn, goal)}
    return {"ok": True, "action": "idle"}


def status() -> dict[str, Any]:
    init_db()
    with connect() as conn:
        day = today_key()
        goals = []
        for row in conn.execute("SELECT * FROM goals ORDER BY priority, id").fetchall():
            goal = row_dict(row)
            goal["today"] = daily_totals(conn, int(goal["id"]), day)
            goals.append(goal)
        events = [row_dict(row) for row in conn.execute("SELECT * FROM controller_events ORDER BY id DESC LIMIT 30").fetchall()]
    rq_summary = rq_get("/api/summary", timeout=12) if RQDB4AI_API_TOKEN else {"ok": False, "error": "RQDB4AI token is not configured"}
    workers = worker_status()
    return {
        "ok": True,
        "enabled": CONTROLLER_ENABLED,
        "today": day,
        "rqdb4ai_api_url": RQDB4AI_API_URL,
        "goals": goals,
        "events": events,
        "rqdb4ai": rq_summary,
        "worker_status": workers,
    }


def set_goal_status(goal_name: str, status_value: str) -> dict[str, Any]:
    init_db()
    if status_value not in {"waiting", "hold", "cooldown", "complete_today"}:
        raise ValueError("invalid goal status")
    with connect() as conn:
        conn.execute(
            "UPDATE goals SET status = ?, current_job_id = '', updated_at = ? WHERE goal_name = ?",
            (status_value, utc_now(), goal_name),
        )
        if conn.total_changes < 1:
            raise KeyError(goal_name)
    event("info", f"goal {goal_name} set to {status_value}", {})
    return {"ok": True, "goal_name": goal_name, "status": status_value}


def run_forever() -> None:
    init_db()
    event("info", "kdeck controller started", {"tick_seconds": TICK_SECONDS, "enabled": CONTROLLER_ENABLED})
    while True:
        try:
            tick()
        except Exception as exc:
            event("error", "controller tick failed", {"error": str(exc)})
        time.sleep(max(5, TICK_SECONDS))


if __name__ == "__main__":
    run_forever()
