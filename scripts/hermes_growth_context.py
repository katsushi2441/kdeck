#!/usr/bin/env python3
from __future__ import annotations

import json
import os
import sqlite3
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app import controller
KGROWTH_PLAN = Path(os.environ.get("KDECK_KGROWTH_PLAN", "")).expanduser() if os.environ.get("KDECK_KGROWTH_PLAN") else None
KGROWTH_JOBS = controller.KGROWTH_IMPROVEMENT_JOBS_PATH


def compact_goal(goal: dict) -> dict:
    return {
        "goal_name": goal.get("goal_name"),
        "status": goal.get("status"),
        "enabled": goal.get("enabled"),
        "priority": goal.get("priority"),
        "today": goal.get("today"),
        "current_job_id": goal.get("current_job_id"),
        "next_action": goal.get("next_action"),
        "next_reason": goal.get("next_reason"),
        "last_note": goal.get("last_note"),
    }


def compact_event(event: dict) -> dict:
    return {
        "level": event.get("level"),
        "message": event.get("message"),
        "created_at": event.get("created_at"),
    }


def latest_kgrowth_jobs(limit: int = 5) -> list[dict]:
    if KGROWTH_JOBS is None or not KGROWTH_JOBS.is_file():
        return []
    try:
        payload = json.loads(KGROWTH_JOBS.read_text(encoding="utf-8"))
    except Exception:
        return []
    out = []
    for job in payload.get("jobs", [])[:limit]:
        if not isinstance(job, dict):
            continue
        out.append({
            "id": job.get("id"),
            "kind": job.get("kind"),
            "title": job.get("title"),
            "priority": job.get("priority"),
            "target_app": job.get("target_app"),
            "action": job.get("action"),
            "success_rule": job.get("success_rule"),
        })
    return out


def plan_excerpt(limit: int = 800) -> str:
    if KGROWTH_PLAN is None or not KGROWTH_PLAN.is_file():
        return ""
    text = KGROWTH_PLAN.read_text(encoding="utf-8", errors="replace")
    return text[:limit]


def main() -> None:
    controller.init_db()
    status = controller.status()
    raw_goals = status.get("goals", [])
    active_goals = [
        compact_goal(goal)
        for goal in raw_goals
        if goal.get("status") in {"waiting", "running", "cooldown", "complete_today"}
    ]
    held_count = sum(1 for goal in raw_goals if goal.get("status") == "hold")
    payload = {
        "kdeck_status": {
            "today": status.get("today"),
            "summary": status.get("summary"),
            "active_goals": active_goals[:12],
            "held_goal_count": held_count,
            "events": [compact_event(event) for event in status.get("events", [])[:5]],
            "rqdb4ai": {
                "summary": (status.get("rqdb4ai") or {}).get("summary"),
                "totals": (status.get("rqdb4ai") or {}).get("totals"),
            },
        },
        "kgrowth": {
            "improvement_jobs": latest_kgrowth_jobs(),
            "plan_excerpt": plan_excerpt(),
        },
        "recommended_primary_command": "python3 -m app.commander_tool growth-cycle",
        "notes": [
            "Use kdeck commander_tool for all Goal Queue state-changing operations.",
            "Non-kgrowth goals run until their same-day business targets are met.",
            "kgrowth stays in a 24/365 log-analysis -> plan -> improvement-job loop.",
            "Use Codex/OpenClaw only when an implementation is missing.",
            "Do not enqueue the same goal twice; use KDECK_MAX_ACTIVE_GOALS for overall capacity.",
        ],
    }
    print(json.dumps(payload, ensure_ascii=False, indent=2, default=str))


if __name__ == "__main__":
    main()
