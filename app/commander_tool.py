from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from typing import Any

from app import controller

ENABLED_GOALS = "enabled = 1"
REFRESHABLE_GOALS = f"{ENABLED_GOALS} AND (status = 'running' OR (status = 'hold' AND current_job_id != ''))"
KGROWTH_ENABLED = "enabled = 1 AND goal_name LIKE 'kgrowth-%'"


def print_json(data: dict[str, Any]) -> None:
    print(json.dumps(data, ensure_ascii=False, indent=2, default=str))


def goal_by_name(conn: sqlite3.Connection, goal_name: str) -> dict[str, Any]:
    row = conn.execute("SELECT * FROM goals WHERE goal_name = ?", (goal_name,)).fetchone()
    if row is None:
        raise SystemExit(f"goal not found: {goal_name}")
    return controller.row_dict(row)


def blocked_reason(conn: sqlite3.Connection, goal: dict[str, Any], day: str) -> tuple[str, dict[str, int]]:
    totals = controller.daily_totals(conn, int(goal["id"]), day)
    status_value = str(goal.get("status") or "")
    if status_value == "running" or controller.latest_open_goal_run(conn, int(goal["id"])):
        return "running", totals
    if status_value == "hold":
        return "hold", totals
    if status_value == "completed" and controller.is_kgrowth_goal(goal):
        return "completed", totals
    if controller.is_kgrowth_goal(goal) and controller.goal_has_successful_run(conn, int(goal["id"])):
        return "kgrowth_completed", totals
    if controller.daily_target_reached(goal, totals):
        return "daily_target_complete", totals
    if controller.daily_run_limit_reached(goal, totals):
        return "max_runs_reached", totals
    if not controller.cooldown_ready(goal):
        return "cooldown", totals
    return "", totals


def running_goal_count(conn: sqlite3.Connection) -> int:
    row = conn.execute(f"SELECT COUNT(*) AS c FROM goals WHERE {ENABLED_GOALS} AND status = 'running'").fetchone()
    return int((row or {})["c"] or 0)


def same_goal_running(conn: sqlite3.Connection, goal_name: str) -> dict[str, Any] | None:
    row = conn.execute(
        f"SELECT goal_name, current_job_id FROM goals WHERE {ENABLED_GOALS} AND goal_name = ? AND status = 'running' LIMIT 1",
        (goal_name,),
    ).fetchone()
    return dict(row) if row is not None else None


def command_status(_args: argparse.Namespace) -> None:
    controller.init_db()
    print_json(controller.status())


def command_sync_kgrowth(_args: argparse.Namespace) -> None:
    controller.init_db()
    with controller.connect() as conn:
        result = controller.sync_kgrowth_improvement_goals(conn)
        enabled = controller.enable_executable_kgrowth_goals(conn)
    data = controller.status()
    data["sync_kgrowth"] = result
    data["enable_executable_kgrowth"] = enabled
    print_json(data)


def command_kgrowth_weekly(args: argparse.Namespace) -> None:
    controller.init_db()
    with controller.connect() as conn:
        weekly = controller.run_kgrowth_weekly(conn, force=args.force)
        sync = controller.sync_kgrowth_improvement_goals(conn)
        enabled = controller.enable_executable_kgrowth_goals(conn)
    print_json({
        "ok": True,
        "kgrowth_weekly": weekly,
        "sync_kgrowth": sync,
        "enable_executable_kgrowth": enabled,
        "status": controller.status(),
    })


def command_refresh(_args: argparse.Namespace) -> None:
    controller.init_db()
    changed: list[dict[str, Any]] = []
    with controller.connect() as conn:
        rows = conn.execute(f"SELECT * FROM goals WHERE {REFRESHABLE_GOALS} ORDER BY priority, id").fetchall()
        for row in rows:
            goal = controller.row_dict(row)
            changed.append({
                "goal_name": goal["goal_name"],
                "changed": controller.refresh_running_goal(conn, goal),
            })
    data = controller.status()
    data["refresh"] = changed
    print_json(data)


def command_brief(_args: argparse.Namespace) -> None:
    controller.init_db()
    changed: list[dict[str, Any]] = []
    with controller.connect() as conn:
        rows = conn.execute(f"SELECT * FROM goals WHERE {REFRESHABLE_GOALS} ORDER BY priority, id").fetchall()
        for row in rows:
            goal = controller.row_dict(row)
            changed.append({
                "goal_name": goal["goal_name"],
                "changed": controller.refresh_running_goal(conn, goal),
            })
        day = controller.today_key()
        goals = []
        running_goal: dict[str, Any] | None = None
        first_eligible_goal: dict[str, Any] | None = None
        for row in conn.execute(f"SELECT * FROM goals WHERE {ENABLED_GOALS} ORDER BY priority, id").fetchall():
            goal = controller.row_dict(row)
            reason, totals = blocked_reason(conn, goal, day)
            display_status = str(goal.get("status") or "")
            if not reason and display_status in {"complete_today", "limit_today", "cooldown"}:
                display_status = "waiting"
            brief_goal = {
                "goal_name": goal["goal_name"],
                "priority": goal["priority"],
                "status": display_status,
                "eligible": not reason,
                "blocked_reason": reason,
                "today_items": totals["items"],
                "today_runs": totals["runs"],
                "daily_target": goal["daily_target"],
                "per_run_target": goal["per_run_target"],
                "max_runs_per_day": goal["max_runs_per_day"],
                "cooldown_until": goal.get("cooldown_until") or "",
                "current_job_id": goal.get("current_job_id") or "",
                "last_note": goal.get("last_note") or "",
            }
            goals.append(brief_goal)
            if running_goal is None and reason == "running":
                running_goal = brief_goal
            if first_eligible_goal is None and not reason:
                first_eligible_goal = brief_goal
        next_goal = running_goal or first_eligible_goal
    print_json({
        "ok": True,
        "today": controller.today_key(),
        "refresh": changed,
        "next_goal": next_goal,
        "goals": goals,
    })


def command_enqueue(args: argparse.Namespace) -> None:
    controller.init_db()
    with controller.connect() as conn:
        active = same_goal_running(conn, args.goal_name)
        if active is not None:
            print_json({"ok": False, "error": "same_goal_running", "running": active})
            return
        active_count = running_goal_count(conn)
        if active_count >= controller.MAX_ACTIVE_GOALS and not args.force:
            print_json({"ok": False, "error": "max_active_goals", "running": active_count, "max_active_goals": controller.MAX_ACTIVE_GOALS})
            return
        goal = goal_by_name(conn, args.goal_name)
        reason, totals = blocked_reason(conn, goal, controller.today_key())
        if reason in {"completed", "kgrowth_completed", "daily_target_complete", "max_runs_reached", "hold", "running"}:
            print_json({"ok": False, "error": reason, "goal_name": goal["goal_name"], "today": totals, "note": goal.get("last_note")})
            return
        if reason == "cooldown" and not args.force:
            print_json({"ok": False, "error": "cooldown", "goal_name": goal["goal_name"], "cooldown_until": goal.get("cooldown_until")})
            return
        response = controller.enqueue_goal(conn, goal)
    print_json({"ok": True, "action": "enqueue", "goal_name": args.goal_name, "response": response})


def command_run_once(_args: argparse.Namespace) -> None:
    controller.init_db()
    with controller.connect() as conn:
        running_rows = conn.execute(f"SELECT * FROM goals WHERE {REFRESHABLE_GOALS} ORDER BY priority, id").fetchall()
        refreshed: list[dict[str, Any]] = []
        for row in running_rows:
            goal = controller.row_dict(row)
            refreshed.append({
                "goal_name": goal["goal_name"],
                "changed": controller.refresh_running_goal(conn, goal),
            })

        active_count = running_goal_count(conn)
        if active_count >= controller.MAX_ACTIVE_GOALS:
            running_rows = conn.execute(f"SELECT goal_name, current_job_id FROM goals WHERE {ENABLED_GOALS} AND status = 'running' ORDER BY priority, id").fetchall()
            print_json({
                "ok": True,
                "action": "wait_capacity",
                "running": [dict(row) for row in running_rows],
                "running_count": active_count,
                "max_active_goals": controller.MAX_ACTIVE_GOALS,
                "refresh": refreshed,
            })
            return

        day = controller.today_key()
        for row in conn.execute(f"SELECT * FROM goals WHERE {ENABLED_GOALS} ORDER BY priority, id").fetchall():
            goal = controller.row_dict(row)
            reason, totals = blocked_reason(conn, goal, day)
            if reason in {"completed", "kgrowth_completed", "hold", "running"}:
                continue
            if reason == "daily_target_complete":
                conn.execute(
                    "UPDATE goals SET status = 'complete_today', last_note = ?, updated_at = ? WHERE id = ?",
                    (f"daily target complete: {totals['items']}/{goal['daily_target']}", controller.utc_now(), goal["id"]),
                )
                continue
            if reason == "max_runs_reached":
                conn.execute(
                    "UPDATE goals SET status = 'limit_today', last_note = ?, updated_at = ? WHERE id = ?",
                    (f"daily run limit reached: runs={totals['runs']} items={totals['items']}/{goal['daily_target']}", controller.utc_now(), goal["id"]),
                )
                continue
            if reason == "cooldown":
                conn.execute("UPDATE goals SET status = 'cooldown', updated_at = ? WHERE id = ?", (controller.utc_now(), goal["id"]))
                continue
            response = controller.enqueue_goal(conn, goal)
            print_json({"ok": True, "action": "enqueue", "goal_name": goal["goal_name"], "response": response, "refresh": refreshed})
            return
    print_json({"ok": True, "action": "idle", "refresh": refreshed})


def latest_finished_goal_run_at(conn: sqlite3.Connection) -> str:
    row = conn.execute(
        """
        SELECT MAX(finished_at) AS finished_at
        FROM goal_runs
        JOIN goals ON goals.id = goal_runs.goal_id
        WHERE finished_at != ''
          AND goals.goal_name LIKE 'kgrowth-%'
          AND (goal_runs.ok = 1 OR goal_runs.business_status = 'ok')
        """
    ).fetchone()
    return str((row or {})["finished_at"] or "") if row else ""


def should_force_kgrowth_after_completion(conn: sqlite3.Connection, _day: str) -> bool:
    latest_finished = controller.parse_iso_datetime(latest_finished_goal_run_at(conn))
    if latest_finished is None:
        return False
    last_kgrowth = controller.last_kgrowth_run_at(conn)
    return last_kgrowth is None or latest_finished > last_kgrowth


def command_growth_cycle(args: argparse.Namespace) -> None:
    controller.init_db()
    with controller.connect() as conn:
        running_rows = conn.execute(f"SELECT * FROM goals WHERE {REFRESHABLE_GOALS} ORDER BY priority, id").fetchall()
        refreshed: list[dict[str, Any]] = []
        for row in running_rows:
            goal = controller.row_dict(row)
            refreshed.append({
                "goal_name": goal["goal_name"],
                "changed": controller.refresh_running_goal(conn, goal),
            })

        active_count = running_goal_count(conn)
        if active_count >= controller.MAX_ACTIVE_GOALS:
            running_rows = conn.execute(f"SELECT goal_name, current_job_id FROM goals WHERE {ENABLED_GOALS} AND status = 'running' ORDER BY priority, id").fetchall()
            print_json({
                "ok": True,
                "action": "wait_capacity",
                "running": [dict(row) for row in running_rows],
                "running_count": active_count,
                "max_active_goals": controller.MAX_ACTIVE_GOALS,
                "refresh": refreshed,
            })
            return

        day = controller.today_key()
        kgrowth_ran = None
        kgrowth_sync = None
        kgrowth_enabled = None
        if args.force_kgrowth or should_force_kgrowth_after_completion(conn, day):
            kgrowth_ran = controller.run_kgrowth_weekly(conn, force=True)
            kgrowth_sync = controller.sync_kgrowth_improvement_goals(conn)
            kgrowth_enabled = controller.enable_executable_kgrowth_goals(conn)

        for row in conn.execute(f"SELECT * FROM goals WHERE {ENABLED_GOALS} ORDER BY priority, id").fetchall():
            goal = controller.row_dict(row)
            reason, totals = blocked_reason(conn, goal, day)
            if reason in {"completed", "kgrowth_completed", "hold", "running"}:
                continue
            if reason == "daily_target_complete":
                conn.execute(
                    "UPDATE goals SET status = 'complete_today', last_note = ?, updated_at = ? WHERE id = ?",
                    (f"daily target complete: {totals['items']}/{goal['daily_target']}", controller.utc_now(), goal["id"]),
                )
                continue
            if reason == "max_runs_reached":
                conn.execute(
                    "UPDATE goals SET status = 'limit_today', last_note = ?, updated_at = ? WHERE id = ?",
                    (f"daily run limit reached: runs={totals['runs']} items={totals['items']}/{goal['daily_target']}", controller.utc_now(), goal["id"]),
                )
                continue
            if reason == "cooldown":
                conn.execute("UPDATE goals SET status = 'cooldown', updated_at = ? WHERE id = ?", (controller.utc_now(), goal["id"]))
                if goal.get("cooldown_until"):
                    refreshed.append({
                        "goal_name": goal["goal_name"],
                        "changed": False,
                        "state": "cooldown",
                        "cooldown_until": goal.get("cooldown_until"),
                    })
                continue
            response = controller.enqueue_goal(conn, goal)
            print_json({
                "ok": True,
                "action": "kgrowth_then_enqueue" if kgrowth_ran else "enqueue",
                "goal_name": goal["goal_name"],
                "response": response,
                "refresh": refreshed,
                "kgrowth_weekly": kgrowth_ran,
                "sync_kgrowth": kgrowth_sync,
                "enable_executable_kgrowth": kgrowth_enabled,
            })
            return

        cooldown_rows = conn.execute(
            """
            SELECT goal_name, cooldown_until
            FROM goals
            WHERE enabled = 1
              AND status = 'cooldown'
              AND cooldown_until != ''
            ORDER BY cooldown_until, priority, id
            """
        ).fetchall()
        live_cooldowns = [
            {"goal_name": row["goal_name"], "cooldown_until": row["cooldown_until"]}
            for row in cooldown_rows
            if not controller.cooldown_ready({"cooldown_until": row["cooldown_until"]})
        ]
        if live_cooldowns:
            print_json({
                "ok": True,
                "action": "wait_cooldown",
                "refresh": refreshed,
                "next": live_cooldowns[0],
                "cooldowns": live_cooldowns[:8],
                "note": "Goal Queue is not finished; waiting for the next cooldown before running kgrowth again.",
            })
            return

        weekly = kgrowth_ran or controller.run_kgrowth_weekly(conn, force=bool(args.force_kgrowth))
        sync = kgrowth_sync or controller.sync_kgrowth_improvement_goals(conn)
        enabled = kgrowth_enabled or controller.enable_executable_kgrowth_goals(conn)
        enqueued = None
        for row in conn.execute(f"SELECT * FROM goals WHERE {ENABLED_GOALS} ORDER BY priority, id").fetchall():
            goal = controller.row_dict(row)
            reason, _totals = blocked_reason(conn, goal, day)
            if reason:
                continue
            enqueued = {"goal_name": goal["goal_name"], "response": controller.enqueue_goal(conn, goal)}
            break
    print_json({
        "ok": True,
        "action": "kgrowth_then_enqueue" if enqueued else "kgrowth_only",
        "refresh": refreshed,
        "kgrowth_weekly": weekly,
        "sync_kgrowth": sync,
        "enable_executable_kgrowth": enabled,
        "enqueue": enqueued,
    })


def command_hold(args: argparse.Namespace) -> None:
    print_json(controller.set_goal_status(args.goal_name, "hold"))


def command_resume(args: argparse.Namespace) -> None:
    print_json(controller.set_goal_status(args.goal_name, "waiting"))


def command_event(args: argparse.Namespace) -> None:
    try:
        data = json.loads(args.data) if args.data else {}
    except json.JSONDecodeError:
        data = {"raw": args.data}
    controller.event(args.level, args.message, data)
    print_json({"ok": True})


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Safe kdeck Goal Queue tool for Hermes commander")
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("status").set_defaults(func=command_status)
    sub.add_parser("sync-kgrowth").set_defaults(func=command_sync_kgrowth)
    kgrowth_weekly = sub.add_parser("kgrowth-weekly")
    kgrowth_weekly.add_argument("--force", action="store_true")
    kgrowth_weekly.set_defaults(func=command_kgrowth_weekly)
    sub.add_parser("refresh").set_defaults(func=command_refresh)
    sub.add_parser("brief").set_defaults(func=command_brief)

    enqueue = sub.add_parser("enqueue")
    enqueue.add_argument("goal_name")
    enqueue.add_argument("--force", action="store_true")
    enqueue.set_defaults(func=command_enqueue)

    sub.add_parser("run-once").set_defaults(func=command_run_once)
    growth_cycle = sub.add_parser("growth-cycle")
    growth_cycle.add_argument("--force-kgrowth", action="store_true")
    growth_cycle.set_defaults(func=command_growth_cycle)

    hold = sub.add_parser("hold")
    hold.add_argument("goal_name")
    hold.set_defaults(func=command_hold)

    resume = sub.add_parser("resume")
    resume.add_argument("goal_name")
    resume.set_defaults(func=command_resume)

    event = sub.add_parser("event")
    event.add_argument("level")
    event.add_argument("message")
    event.add_argument("--data", default="{}")
    event.set_defaults(func=command_event)
    return parser


def main(argv: list[str] | None = None) -> None:
    args = build_parser().parse_args(argv)
    args.func(args)


if __name__ == "__main__":
    main(sys.argv[1:])
