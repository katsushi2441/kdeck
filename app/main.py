from __future__ import annotations

import os
import pty
import re
import secrets
import select
import signal
import subprocess
import threading
import time
import uuid
from collections import deque
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


class Session:
    def __init__(self, session_id: str, name: str, cwd: Path, command: str):
        self.id = session_id
        self.name = name
        self.cwd = cwd
        self.command = command
        self.created = int(time.time())
        self.master_fd: int | None = None
        self.process: subprocess.Popen[bytes] | None = None
        self.output: deque[str] = deque(maxlen=25000)
        self.lock = threading.Lock()

    @property
    def alive(self) -> bool:
        return self.process is not None and self.process.poll() is None

    def start(self) -> None:
        master_fd, slave_fd = pty.openpty()
        self.master_fd = master_fd
        self.process = subprocess.Popen(
            self.command,
            cwd=str(self.cwd),
            shell=True,
            stdin=slave_fd,
            stdout=slave_fd,
            stderr=slave_fd,
            start_new_session=True,
        )
        os.close(slave_fd)
        thread = threading.Thread(target=self._reader, daemon=True)
        thread.start()

    def _reader(self) -> None:
        assert self.master_fd is not None
        while True:
            if self.process is not None and self.process.poll() is not None:
                break
            try:
                ready, _, _ = select.select([self.master_fd], [], [], 0.5)
                if not ready:
                    continue
                data = os.read(self.master_fd, 8192)
                if not data:
                    break
                text = data.decode("utf-8", errors="replace")
                with self.lock:
                    self.output.append(text)
            except OSError:
                break
        code = self.process.poll() if self.process else None
        with self.lock:
            self.output.append(f"\n[process exited: {code}]\n")

    def capture(self, max_chars: int = 120000) -> str:
        with self.lock:
            text = "".join(self.output)
        if len(text) > max_chars:
            text = text[-max_chars:]
        return text

    def send(self, text: str, enter: bool = True) -> None:
        if self.master_fd is None or not self.alive:
            raise HTTPException(status_code=409, detail="session is not running")
        payload = text + ("\n" if enter else "")
        os.write(self.master_fd, payload.encode("utf-8"))

    def interrupt(self) -> None:
        if self.process is None or not self.alive:
            raise HTTPException(status_code=409, detail="session is not running")
        os.killpg(self.process.pid, signal.SIGINT)


SESSIONS: dict[str, Session] = {}


def require_auth(authorization: str = Header(default="")) -> None:
    if not TOKEN or TOKEN == "change-this-token":
        raise HTTPException(status_code=500, detail="KDECK_TOKEN is not configured")
    prefix = "Bearer "
    if not authorization.startswith(prefix):
        raise HTTPException(status_code=401, detail="missing bearer token")
    if not secrets.compare_digest(authorization[len(prefix):], TOKEN):
        raise HTTPException(status_code=403, detail="invalid token")


def safe_name(name: str) -> str:
    cleaned = re.sub(r"[^a-zA-Z0-9_-]+", "-", name.strip().lower()).strip("-")
    return cleaned or "codex"


def session_id_for(name: str) -> str:
    return f"{SESSION_PREFIX}{safe_name(name)}-{uuid.uuid4().hex[:8]}"


def validate_cwd(cwd: str) -> Path:
    path = Path(cwd).expanduser().resolve()
    if not path.exists() or not path.is_dir():
        raise HTTPException(status_code=400, detail="cwd does not exist")
    for root in ALLOWED_ROOTS:
        if path == root or root in path.parents:
            return path
    raise HTTPException(status_code=400, detail="cwd is not allowed")


def get_session(session_id: str) -> Session:
    if not session_id.startswith(SESSION_PREFIX) or session_id not in SESSIONS:
        raise HTTPException(status_code=404, detail="session not found")
    return SESSIONS[session_id]


def list_sessions() -> list[dict[str, Any]]:
    for session_id, session in list(SESSIONS.items()):
        if not session.alive:
            SESSIONS.pop(session_id, None)
    items = []
    for s in sorted(SESSIONS.values(), key=lambda item: item.created, reverse=True):
        items.append({
            "id": s.id,
            "name": s.name,
            "cwd": str(s.cwd),
            "command": s.command,
            "created": s.created,
            "alive": s.alive,
            "attached": 0,
        })
    return items


@app.get("/healthz")
def healthz() -> dict[str, Any]:
    return {"ok": True, "service": "kdeck", "name": APP_NAME, "port": int(os.environ.get("KDECK_PORT", "18301"))}


@app.get("/api/config", dependencies=[Depends(require_auth)])
def config() -> dict[str, Any]:
    return {"ok": True, "allowed_roots": [str(p) for p in ALLOWED_ROOTS], "codex_cmd": CODEX_CMD, "backend": "pty"}


@app.get("/api/sessions", dependencies=[Depends(require_auth)])
def sessions() -> dict[str, Any]:
    return {"ok": True, "sessions": list_sessions()}


@app.post("/api/sessions", dependencies=[Depends(require_auth)])
def create_session(req: CreateSessionRequest) -> dict[str, Any]:
    cwd = validate_cwd(req.cwd)
    name = safe_name(req.name)
    command = req.command.strip() or CODEX_CMD
    session = Session(session_id_for(name), name, cwd, command)
    session.start()
    SESSIONS[session.id] = session
    time.sleep(0.2)
    return {"ok": True, "id": session.id, "cwd": str(cwd), "command": command}


@app.get("/api/sessions/{session_id}/capture", dependencies=[Depends(require_auth)])
def capture(session_id: str, lines: int = 800) -> dict[str, Any]:
    session = get_session(session_id)
    return {"ok": True, "id": session.id, "alive": session.alive, "text": session.capture()}


@app.post("/api/sessions/{session_id}/send", dependencies=[Depends(require_auth)])
def send(session_id: str, req: SendRequest) -> dict[str, Any]:
    session = get_session(session_id)
    session.send(req.text, req.enter)
    return {"ok": True, "id": session.id}


@app.post("/api/sessions/{session_id}/interrupt", dependencies=[Depends(require_auth)])
def interrupt(session_id: str) -> dict[str, Any]:
    session = get_session(session_id)
    session.interrupt()
    return {"ok": True, "id": session.id}


@app.post("/api/sessions/{session_id}/terminate", dependencies=[Depends(require_auth)])
def terminate(session_id: str) -> dict[str, Any]:
    session = get_session(session_id)
    if session.process is not None and session.alive:
        os.killpg(session.process.pid, signal.SIGTERM)
        try:
            session.process.wait(timeout=3)
        except subprocess.TimeoutExpired:
            os.killpg(session.process.pid, signal.SIGKILL)
    SESSIONS.pop(session_id, None)
    return {"ok": True, "id": session.id}
