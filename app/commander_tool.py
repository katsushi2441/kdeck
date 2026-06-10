from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from typing import Any

from app import controller


def print_json(data: dict[str, Any]) -> None:
    print(json.dumps(data, ensure_ascii=False, indent=2, default=str))


def goal_by_name(conn: sqlite3.Connection, goal_name: str) -> dict[str, Any]:
    row = conn.execute("SELECT * FROM goals WHERE goal_name = ?", (goal_name,)).fetchone()
    if row is None:
        raise SystemExit(f"goal not found: {goal_name}")
    return controller.row_dict(row)


def command_status(_args: argparse.Namespace) -> None:
    controller.init_db()
    print_json(controller.status())


def command_sync_kgrowth(_args: argparse.Namespace) -> None:
    controller.init_db()
    with controller.connect() as conn:
        result = controller.sync_kgrowth_improvement_goals(conn)
    data = controller.status()
    data["sync_kgrowth"] = result
    print_json(data)


def command_refresh(_args: argparse.Namespace) -> None:
    controller.init_db()
    changed: list[dict[str, Any]] = []
    with controller.connect() as conn:
        rows = conn.execute("SELECT * FROM goals WHERE enabled = 1 AND status = 'running' ORDER BY priority, id").fetchall()
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
        rows = conn.execute("SELECT * FROM goals WHERE enabled = 1 AND status = 'running' ORDER BY priority, id").fetchall()
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
        for row in conn.execute("SELECT * FROM goals WHERE enabled = 1 ORDER BY priority, id").fetchall():
            goal = controller.row_dict(row)
            totals = controller.daily_totals(conn, int(goal["id"]), day)
            blocked_reason = ""
            if totals["items"] >= int(goal.get("daily_target") or 1):
                blocked_reason = "daily_target_complete"
            elif totals["runs"] >= int(goal.get("max_runs_per_day") or 1):
                blocked_reason = "max_runs_reached"
            elif str(goal.get("status")) == "hold":
                blocked_reason = "hold"
            elif str(goal.get("status")) == "running":
                blocked_reason = "running"
            elif not controller.cooldown_ready(goal):
                blocked_reason = "cooldown"
            display_status = str(goal.get("status") or "")
            if not blocked_reason and display_status == "complete_today":
                display_status = "waiting"
            brief_goal = {
                "goal_name": goal["goal_name"],
                "priority": goal["priority"],
                "status": display_status,
                "eligible": not blocked_reason,
                "blocked_reason": blocked_reason,
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
            if running_goal is None and blocked_reason == "running":
                running_goal = brief_goal
            if first_eligible_goal is None and not blocked_reason:
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
        active = conn.execute("SELECT goal_name, current_job_id FROM goals WHERE enabled = 1 AND status = 'running' ORDER BY priority, id").fetchone()
        if active is not None:
            print_json({"ok": False, "error": "another_goal_running", "running": dict(active)})
            return
        goal = goal_by_name(conn, args.goal_name)
        totals = controller.daily_totals(conn, int(goal["id"]), controller.today_key())
        if totals["items"] >= int(goal.get("daily_target") or 1):
            print_json({"ok": False, "error": "daily_target_complete", "goal_name": goal["goal_name"], "today": totals})
            return
        if totals["runs"] >= int(goal.get("max_runs_per_day") or 1):
            print_json({"ok": False, "error": "max_runs_reached", "goal_name": goal["goal_name"], "today": totals})
            return
        if str(goal.get("status")) == "hold":
            print_json({"ok": False, "error": "goal_on_hold", "goal_name": goal["goal_name"], "note": goal.get("last_note")})
            return
        if not controller.cooldown_ready(goal) and not args.force:
            print_json({"ok": False, "error": "cooldown", "goal_name": goal["goal_name"], "cooldown_until": goal.get("cooldown_until")})
            return
        response = controller.enqueue_goal(conn, goal)
    print_json({"ok": True, "action": "enqueue", "goal_name": args.goal_name, "response": response})


def command_run_once(_args: argparse.Namespace) -> None:
    controller.init_db()
    with controller.connect() as conn:
        running_rows = conn.execute("SELECT * FROM goals WHERE enabled = 1 AND status = 'running' ORDER BY priority, id").fetchall()
        refreshed: list[dict[str, Any]] = []
        for row in running_rows:
            goal = controller.row_dict(row)
            refreshed.append({
                "goal_name": goal["goal_name"],
                "changed": controller.refresh_running_goal(conn, goal),
            })

        running = conn.execute("SELECT goal_name, current_job_id FROM goals WHERE enabled = 1 AND status = 'running' ORDER BY priority, id LIMIT 1").fetchone()
        if running is not None:
            print_json({"ok": True, "action": "wait_running", "running": dict(running), "refresh": refreshed})
            return

        day = controller.today_key()
        for row in conn.execute("SELECT * FROM goals WHERE enabled = 1 ORDER BY priority, id").fetchall():
            goal = controller.row_dict(row)
            totals = controller.daily_totals(conn, int(goal["id"]), day)
            if totals["items"] >= int(goal.get("daily_target") or 1):
                conn.execute(
                    "UPDATE goals SET status = 'complete_today', last_note = ?, updated_at = ? WHERE id = ?",
                    (f"daily target complete: {totals['items']}/{goal['daily_target']}", controller.utc_now(), goal["id"]),
                )
                continue
            if totals["runs"] >= int(goal.get("max_runs_per_day") or 1):
                conn.execute(
                    "UPDATE goals SET status = 'complete_today', last_note = ?, updated_at = ? WHERE id = ?",
                    (f"max runs reached: runs={totals['runs']} items={totals['items']}/{goal['daily_target']}", controller.utc_now(), goal["id"]),
                )
                continue
            if str(goal.get("status")) == "hold":
                continue
            if not controller.cooldown_ready(goal):
                conn.execute("UPDATE goals SET status = 'cooldown', updated_at = ? WHERE id = ?", (controller.utc_now(), goal["id"]))
                continue
            response = controller.enqueue_goal(conn, goal)
            print_json({"ok": True, "action": "enqueue", "goal_name": goal["goal_name"], "response": response, "refresh": refreshed})
            return
    print_json({"ok": True, "action": "idle", "refresh": refreshed})


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
    sub.add_parser("refresh").set_defaults(func=command_refresh)
    sub.add_parser("brief").set_defaults(func=command_brief)

    enqueue = sub.add_parser("enqueue")
    enqueue.add_argument("goal_name")
    enqueue.add_argument("--force", action="store_true")
    enqueue.set_defaults(func=command_enqueue)

    sub.add_parser("run-once").set_defaults(func=command_run_once)

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
