from __future__ import annotations

import asyncio
import os
import pty
import queue
import json
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
from fastapi import Depends, FastAPI, Header, HTTPException, WebSocket, WebSocketDisconnect
from pydantic import BaseModel, Field

load_dotenv(Path(__file__).resolve().parents[1] / ".env")

APP_NAME = "Kurage Agent Deck"
SESSION_PREFIX = "kdeck-"
TOKEN = os.environ.get("KDECK_TOKEN", "")
CODEX_CMD = os.environ.get("KDECK_CODEX_CMD", "codex")
CODEX_MODEL = os.environ.get("KDECK_CODEX_MODEL", "gpt-5.4-mini")
CODEX_SANDBOX = os.environ.get("KDECK_CODEX_SANDBOX", "workspace-write")
DATA_DIR = Path(os.environ.get("KDECK_DATA_DIR", Path(__file__).resolve().parents[1] / "storage")).expanduser()
CHAT_DIR = DATA_DIR / "chat_threads"
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


class ChatRequest(BaseModel):
    prompt: str = Field(min_length=1, max_length=12000)
    cwd: str = "/home/kojima/work/url2ai"
    thread_id: str = ""
    model: str = ""


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
        self.subscribers: list[queue.Queue[str]] = []

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
                    subscribers = list(self.subscribers)
                for subscriber in subscribers:
                    subscriber.put(text)
            except OSError:
                break
        code = self.process.poll() if self.process else None
        final = f"\n[process exited: {code}]\n"
        with self.lock:
            self.output.append(final)
            subscribers = list(self.subscribers)
        for subscriber in subscribers:
            subscriber.put(final)

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

    def send_raw(self, text: str) -> None:
        if self.master_fd is None or not self.alive:
            return
        os.write(self.master_fd, text.encode("utf-8"))

    def subscribe(self) -> queue.Queue[str]:
        subscriber: queue.Queue[str] = queue.Queue(maxsize=1000)
        with self.lock:
            self.subscribers.append(subscriber)
        return subscriber

    def unsubscribe(self, subscriber: queue.Queue[str]) -> None:
        with self.lock:
            if subscriber in self.subscribers:
                self.subscribers.remove(subscriber)

    def interrupt(self) -> None:
        if self.process is None or not self.alive:
            raise HTTPException(status_code=409, detail="session is not running")
        os.killpg(self.process.pid, signal.SIGINT)


SESSIONS: dict[str, Session] = {}
TICKETS: dict[str, tuple[str, float]] = {}
CHAT_THREADS: dict[str, list[dict[str, str]]] = {}
CHAT_META: dict[str, dict[str, Any]] = {}
CHAT_JOBS: dict[str, dict[str, Any]] = {}


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


def safe_thread_id(thread_id: str) -> str:
    cleaned = re.sub(r"[^a-zA-Z0-9_-]+", "", thread_id.strip())
    if not cleaned.startswith("chat-"):
        return ""
    return cleaned[:80]


def thread_path(thread_id: str) -> Path:
    return CHAT_DIR / f"{thread_id}.json"


def thread_title(messages: list[dict[str, str]]) -> str:
    for message in messages:
        if message.get("role") == "user":
            title = re.sub(r"\s+", " ", message.get("content", "")).strip()
            return title[:52] + ("..." if len(title) > 52 else "")
    return "New chat"


def load_thread(thread_id: str) -> list[dict[str, str]]:
    thread_id = safe_thread_id(thread_id)
    if not thread_id:
        return []
    if thread_id in CHAT_THREADS:
        return CHAT_THREADS[thread_id]
    path = thread_path(thread_id)
    if not path.exists():
        CHAT_THREADS[thread_id] = []
        return CHAT_THREADS[thread_id]
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        messages = payload.get("messages", [])
        if not isinstance(messages, list):
            messages = []
        clean_messages = [
            {"role": str(m.get("role", "")), "content": str(m.get("content", ""))}
            for m in messages
            if isinstance(m, dict) and m.get("role") in {"user", "assistant"}
        ]
        CHAT_THREADS[thread_id] = clean_messages
        CHAT_META[thread_id] = {
            "id": thread_id,
            "title": str(payload.get("title") or thread_title(clean_messages)),
            "cwd": str(payload.get("cwd") or ""),
            "model": str(payload.get("model") or ""),
            "created": int(payload.get("created") or 0),
            "updated": int(payload.get("updated") or 0),
        }
    except Exception:
        CHAT_THREADS[thread_id] = []
    return CHAT_THREADS[thread_id]


def save_thread(thread_id: str, cwd: str, model: str) -> None:
    thread_id = safe_thread_id(thread_id)
    if not thread_id:
        return
    CHAT_DIR.mkdir(parents=True, exist_ok=True)
    messages = CHAT_THREADS.get(thread_id, [])
    now = int(time.time())
    meta = CHAT_META.get(thread_id, {})
    created = int(meta.get("created") or now)
    payload = {
        "id": thread_id,
        "title": thread_title(messages),
        "cwd": cwd,
        "model": model,
        "created": created,
        "updated": now,
        "messages": messages[-80:],
    }
    thread_path(thread_id).write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    CHAT_META[thread_id] = {k: payload[k] for k in ("id", "title", "cwd", "model", "created", "updated")}


def list_chat_threads() -> list[dict[str, Any]]:
    CHAT_DIR.mkdir(parents=True, exist_ok=True)
    items: list[dict[str, Any]] = []
    for path in CHAT_DIR.glob("chat-*.json"):
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
            messages = payload.get("messages") if isinstance(payload.get("messages"), list) else []
            items.append({
                "id": str(payload.get("id") or path.stem),
                "title": str(payload.get("title") or thread_title(messages)),
                "cwd": str(payload.get("cwd") or ""),
                "model": str(payload.get("model") or ""),
                "created": int(payload.get("created") or 0),
                "updated": int(payload.get("updated") or 0),
                "messages": len(messages),
            })
        except Exception:
            continue
    return sorted(items, key=lambda item: item.get("updated") or item.get("created") or 0, reverse=True)[:100]


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


def create_ticket(session_id: str) -> str:
    ticket = secrets.token_urlsafe(24)
    TICKETS[ticket] = (session_id, time.time() + 60)
    for key, (_, expires) in list(TICKETS.items()):
        if expires < time.time():
            TICKETS.pop(key, None)
    return ticket


def consume_ticket(ticket: str, session_id: str) -> bool:
    stored = TICKETS.pop(ticket, None)
    if stored is None:
        return False
    stored_session_id, expires = stored
    return stored_session_id == session_id and expires >= time.time()


@app.get("/healthz")
def healthz() -> dict[str, Any]:
    return {"ok": True, "service": "kdeck", "name": APP_NAME, "port": int(os.environ.get("KDECK_PORT", "18301"))}


@app.get("/api/config", dependencies=[Depends(require_auth)])
def config() -> dict[str, Any]:
    return {"ok": True, "allowed_roots": [str(p) for p in ALLOWED_ROOTS], "codex_cmd": CODEX_CMD, "codex_model": CODEX_MODEL, "backend": "pty"}


def run_codex_exec(cwd: Path, model: str, prompt: str) -> dict[str, Any]:
    cmd = [
        CODEX_CMD,
        "exec",
        "--json",
        "-m",
        model,
        "--cd",
        str(cwd),
        "--sandbox",
        CODEX_SANDBOX,
        "-",
    ]
    proc = subprocess.run(
        cmd,
        input=prompt,
        text=True,
        cwd=str(cwd),
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        timeout=900,
    )
    final_text = ""
    events: list[dict[str, Any]] = []
    for line in proc.stdout.splitlines():
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue
        events.append(event)
        item = event.get("item")
        if event.get("type") == "item.completed" and isinstance(item, dict) and item.get("type") == "agent_message":
            final_text = str(item.get("text", ""))
        if event.get("type") == "turn.failed" and not final_text:
            final_text = str(event.get("error", {}).get("message", "Codex turn failed"))
    if proc.returncode != 0 and not final_text:
        final_text = (proc.stderr or proc.stdout or f"codex exited with {proc.returncode}").strip()
    return {
        "returncode": proc.returncode,
        "text": final_text,
        "stderr_tail": proc.stderr[-4000:],
        "events": events[-20:],
    }


@app.post("/api/chat", dependencies=[Depends(require_auth)])
def chat(req: ChatRequest) -> dict[str, Any]:
    cwd = validate_cwd(req.cwd)
    model = req.model.strip() or CODEX_MODEL
    thread_id = safe_thread_id(req.thread_id) or f"chat-{uuid.uuid4().hex[:8]}"
    job_id = f"chatjob-{uuid.uuid4().hex[:10]}"
    CHAT_JOBS[job_id] = {
        "ok": True,
        "job_id": job_id,
        "thread_id": thread_id,
        "status": "running",
        "model": model,
        "cwd": str(cwd),
        "message": "",
        "error": "",
        "created": int(time.time()),
        "finished": 0,
    }

    def worker() -> None:
        try:
            result = run_chat_turn(cwd, model, thread_id, req.prompt)
            CHAT_JOBS[job_id].update(result)
            CHAT_JOBS[job_id]["status"] = "finished"
            CHAT_JOBS[job_id]["finished"] = int(time.time())
        except Exception as exc:
            CHAT_JOBS[job_id].update({
                "ok": False,
                "status": "failed",
                "error": str(exc),
                "finished": int(time.time()),
            })

    threading.Thread(target=worker, daemon=True).start()
    return CHAT_JOBS[job_id]


def run_chat_turn(cwd: Path, model: str, thread_id: str, user_prompt: str) -> dict[str, Any]:
    history = load_thread(thread_id)
    transcript = "\n\n".join(
        f"{m['role'].upper()}:\n{m['content']}" for m in history[-12:]
    )
    prompt = (
        "You are Codex in Kurage Agent Deck. Answer in Japanese unless the user asks otherwise.\n"
        "Continue the conversation below and act on the selected workspace when needed.\n\n"
        + (transcript + "\n\n" if transcript else "")
        + "USER:\n"
        + user_prompt
    )
    history.append({"role": "user", "content": user_prompt})
    save_thread(thread_id, str(cwd), model)
    result = run_codex_exec(cwd, model, prompt)
    assistant_text = result["text"] or "(no response)"
    history.append({"role": "assistant", "content": assistant_text})
    save_thread(thread_id, str(cwd), model)
    return {
        "ok": result["returncode"] == 0,
        "thread_id": thread_id,
        "model": model,
        "cwd": str(cwd),
        "message": assistant_text,
        "stderr_tail": result["stderr_tail"],
    }


@app.get("/api/chat/{job_id}", dependencies=[Depends(require_auth)])
def chat_job(job_id: str) -> dict[str, Any]:
    job = CHAT_JOBS.get(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="chat job not found")
    return job


@app.get("/api/chat_threads", dependencies=[Depends(require_auth)])
def chat_threads() -> dict[str, Any]:
    return {"ok": True, "threads": list_chat_threads()}


@app.get("/api/chat_threads/{thread_id}", dependencies=[Depends(require_auth)])
def chat_thread(thread_id: str) -> dict[str, Any]:
    thread_id = safe_thread_id(thread_id)
    if not thread_id:
        raise HTTPException(status_code=404, detail="chat thread not found")
    messages = load_thread(thread_id)
    meta = CHAT_META.get(thread_id, {})
    return {
        "ok": True,
        "thread": {
            "id": thread_id,
            "title": meta.get("title") or thread_title(messages),
            "cwd": meta.get("cwd") or "",
            "model": meta.get("model") or "",
            "created": meta.get("created") or 0,
            "updated": meta.get("updated") or 0,
            "messages": messages,
        },
    }


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


@app.post("/api/sessions/{session_id}/ticket", dependencies=[Depends(require_auth)])
def ticket(session_id: str) -> dict[str, Any]:
    session = get_session(session_id)
    if not session.alive:
        raise HTTPException(status_code=409, detail="session is not running")
    return {"ok": True, "id": session.id, "ticket": create_ticket(session.id), "expires_in": 60}


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


@app.websocket("/api/sessions/{session_id}/terminal")
async def terminal(websocket: WebSocket, session_id: str, ticket: str = "") -> None:
    if not consume_ticket(ticket, session_id):
        await websocket.close(code=1008)
        return
    session = get_session(session_id)
    subscriber = session.subscribe()
    await websocket.accept()
    backlog = session.capture()
    if backlog:
        await websocket.send_text(backlog)

    async def send_output() -> None:
        while True:
            text = await asyncio.to_thread(subscriber.get)
            await websocket.send_text(text)

    task = asyncio.create_task(send_output())
    try:
        while True:
            data = await websocket.receive_text()
            session.send_raw(data)
    except WebSocketDisconnect:
        pass
    finally:
        task.cancel()
        session.unsubscribe(subscriber)
