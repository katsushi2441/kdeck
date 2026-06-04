from __future__ import annotations

import os
import re
import secrets
import subprocess
import time
from pathlib import Path
from typing import Any

from dotenv import load_dotenv
from fastapi import Depends, FastAPI, Header, HTTPException
from pydantic import BaseModel, Field

load_dotenv(Path(__file__).resolve().parents[1] / ".env")

APP_NAME = "Kurage Agent Deck"
SESSION_PREFIX = "kdeck-"
TOKEN = os.environ.get("KDECK_TOKEN", "")
CODEX_CMD = os.environ.get("KDECK_CODEX_CMD", "codex")
ALLOWED_ROOTS = [
    Path(p).expanduser().resolve()
    for p in os.environ.get("KDECK_ALLOWED_ROOTS", "/home/kojima/work/url2ai").split(",")
    if p.strip()
]

app = FastAPI(title=APP_NAME)


class CreateSessionRequest(BaseModel):
    name: str = Field(default="codex", max_length=40)
    cwd: str = "/home/kojima/work/url2ai"
    command: str = ""


class SendRequest(BaseModel):
    text: str = Field(min_length=1, max_length=12000)
    enter: bool = True


def require_auth(authorization: str = Header(default="")) -> None:
    if not TOKEN or TOKEN == "change-this-token":
        raise HTTPException(status_code=500, detail="KDECK_TOKEN is not configured")
    prefix = "Bearer "
    if not authorization.startswith(prefix):
        raise HTTPException(status_code=401, detail="missing bearer token")
    if not secrets.compare_digest(authorization[len(prefix):], TOKEN):
        raise HTTPException(status_code=403, detail="invalid token")


def run_tmux(args: list[str], *, input_text: str | None = None, check: bool = True) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["tmux"] + args,
        input=input_text,
        capture_output=True,
        text=True,
        check=check,
    )


def safe_name(name: str) -> str:
    cleaned = re.sub(r"[^a-zA-Z0-9_-]+", "-", name.strip().lower()).strip("-")
    if not cleaned:
        cleaned = "codex"
    return (SESSION_PREFIX + cleaned)[:60]


def validate_cwd(cwd: str) -> Path:
    path = Path(cwd).expanduser().resolve()
    if not path.exists() or not path.is_dir():
        raise HTTPException(status_code=400, detail="cwd does not exist")
    for root in ALLOWED_ROOTS:
        if path == root or root in path.parents:
            return path
    raise HTTPException(status_code=400, detail="cwd is not allowed")


def tmux_exists(session_id: str) -> bool:
    res = run_tmux(["has-session", "-t", session_id], check=False)
    return res.returncode == 0


def list_sessions() -> list[dict[str, Any]]:
    res = run_tmux(["list-sessions", "-F", "#{session_name}\t#{session_created}\t#{session_attached}"], check=False)
    if res.returncode != 0:
        return []
    sessions = []
    for line in res.stdout.splitlines():
        parts = line.split("\t")
        if len(parts) < 3 or not parts[0].startswith(SESSION_PREFIX):
            continue
        session_id = parts[0]
        sessions.append({
            "id": session_id,
            "name": session_id.removeprefix(SESSION_PREFIX),
            "created": int(parts[1] or 0),
            "attached": int(parts[2] or 0),
        })
    return sessions


@app.get("/healthz")
def healthz() -> dict[str, Any]:
    return {"ok": True, "service": "kdeck", "name": APP_NAME, "port": int(os.environ.get("KDECK_PORT", "18301"))}


@app.get("/api/config", dependencies=[Depends(require_auth)])
def config() -> dict[str, Any]:
    return {"ok": True, "allowed_roots": [str(p) for p in ALLOWED_ROOTS], "codex_cmd": CODEX_CMD}


@app.get("/api/sessions", dependencies=[Depends(require_auth)])
def sessions() -> dict[str, Any]:
    return {"ok": True, "sessions": list_sessions()}


@app.post("/api/sessions", dependencies=[Depends(require_auth)])
def create_session(req: CreateSessionRequest) -> dict[str, Any]:
    cwd = validate_cwd(req.cwd)
    session_id = safe_name(req.name)
    if tmux_exists(session_id):
        raise HTTPException(status_code=409, detail="session already exists")
    command = req.command.strip() or CODEX_CMD
    run_tmux(["new-session", "-d", "-s", session_id, "-c", str(cwd), command])
    time.sleep(0.2)
    return {"ok": True, "id": session_id, "cwd": str(cwd), "command": command}


@app.get("/api/sessions/{session_id}/capture", dependencies=[Depends(require_auth)])
def capture(session_id: str, lines: int = 800) -> dict[str, Any]:
    if not session_id.startswith(SESSION_PREFIX) or not tmux_exists(session_id):
        raise HTTPException(status_code=404, detail="session not found")
    lines = max(50, min(5000, int(lines)))
    res = run_tmux(["capture-pane", "-t", session_id, "-p", "-S", f"-{lines}"], check=False)
    return {"ok": res.returncode == 0, "id": session_id, "text": res.stdout, "error": res.stderr}


@app.post("/api/sessions/{session_id}/send", dependencies=[Depends(require_auth)])
def send(session_id: str, req: SendRequest) -> dict[str, Any]:
    if not session_id.startswith(SESSION_PREFIX) or not tmux_exists(session_id):
        raise HTTPException(status_code=404, detail="session not found")
    buffer_name = f"{session_id}-input"
    run_tmux(["set-buffer", "-b", buffer_name, req.text])
    run_tmux(["paste-buffer", "-d", "-b", buffer_name, "-t", session_id])
    if req.enter:
        run_tmux(["send-keys", "-t", session_id, "Enter"])
    return {"ok": True, "id": session_id}


@app.post("/api/sessions/{session_id}/interrupt", dependencies=[Depends(require_auth)])
def interrupt(session_id: str) -> dict[str, Any]:
    if not session_id.startswith(SESSION_PREFIX) or not tmux_exists(session_id):
        raise HTTPException(status_code=404, detail="session not found")
    run_tmux(["send-keys", "-t", session_id, "C-c"])
    return {"ok": True, "id": session_id}
