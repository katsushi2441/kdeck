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
import tempfile
import uuid
import urllib.error
import urllib.request
import shlex
from collections import deque
from pathlib import Path
from typing import Any

from dotenv import load_dotenv
from fastapi import Depends, FastAPI, Header, HTTPException, WebSocket, WebSocketDisconnect
from pydantic import BaseModel, Field

from app import controller

load_dotenv(Path(__file__).resolve().parents[1] / ".env")

APP_NAME = "Kurage Agent Deck"
SESSION_PREFIX = "kdeck-"
TOKEN = os.environ.get("KDECK_TOKEN", "")
CODEX_CMD = os.environ.get("KDECK_CODEX_CMD", "codex")
CODEX_MODEL = os.environ.get("KDECK_CODEX_MODEL", "gpt-5.5")
CODEX_SANDBOX = os.environ.get("KDECK_CODEX_SANDBOX", "workspace-write")
SWARMCLAW_BASE_URL = os.environ.get("SWARMCLAW_BASE_URL", "http://127.0.0.1:3456").rstrip("/")
SWARMCLAW_HOME = os.environ.get("SWARMCLAW_HOME", "/home/kojima/.swarmclaw")
OPENCLAW_CMD = os.environ.get("KDECK_OPENCLAW_CMD", "/home/kojima/.nvm/versions/node/v24.16.0/bin/openclaw")
REMOTE_SSH_KEY = os.environ.get("KDECK_REMOTE_SSH_KEY", "/home/kojima/.ssh/id_swarmclaw_openclaw")
REMOTE_SSH_USER = os.environ.get("KDECK_REMOTE_SSH_USER", "kojima")
REMOTE_SSH_PORT = int(os.environ.get("KDECK_REMOTE_SSH_PORT", "2222"))
REMOTE_CODEX_CANDIDATES = [
    "~/.local/bin/codex",
    "~/.npm-global/bin/codex",
    "/usr/local/bin/codex",
    "/usr/bin/codex",
    "codex",
]
REMOTE_CLAUDE_CANDIDATES = [
    "/usr/bin/claude",
    "/usr/local/bin/claude",
    "~/.local/bin/claude",
    "~/.npm-global/bin/claude",
    "claude",
]
REMOTE_OLLAMA_CANDIDATES = [
    "/usr/local/bin/ollama",
    "/usr/bin/ollama",
    "ollama",
]
REMOTE_BACKEND_DEFAULT_MODELS = {
    "codex-cli": CODEX_MODEL,
    "claude-cli": os.environ.get("KDECK_REMOTE_CLAUDE_MODEL", "claude-sonnet-4-6"),
    "ollama": os.environ.get("KDECK_REMOTE_OLLAMA_MODEL", "gemma4:e4b"),
}
CODEX_EXECUTION_MODES = {
    "chat-only": {
        "label": "Chat only",
        "sandbox": "read-only",
        "description": "議論だけを行い、コマンド実行・ファイル変更・外部操作はしません。",
    },
    "confirm": {
        "label": "確認して実行",
        "sandbox": "workspace-write",
        "description": "送信前に確認し、Codex CLIはworkspace-writeで実行します。",
    },
    "full-access": {
        "label": "Full access",
        "sandbox": "danger-full-access",
        "description": "確認なしでCodex CLIをdanger-full-accessで実行します。",
    },
}
DEFAULT_EXECUTION_MODE = os.environ.get("KDECK_DEFAULT_EXECUTION_MODE", "chat-only").strip() or "chat-only"
if DEFAULT_EXECUTION_MODE not in CODEX_EXECUTION_MODES:
    DEFAULT_EXECUTION_MODE = "chat-only"
DATA_DIR = Path(os.environ.get("KDECK_DATA_DIR", Path(__file__).resolve().parents[1] / "storage")).expanduser()
CHAT_DIR = DATA_DIR / "chat_threads"
TASK_DIR = DATA_DIR / "agent_tasks"
MEMORY_DIR = DATA_DIR / "shared_memory"
CHAT_SAVE_MESSAGE_LIMIT = 120
CHAT_PROMPT_MESSAGE_LIMIT = 80
CHAT_PROMPT_CHAR_LIMIT = 60000
ALLOWED_ROOTS = [
    Path(p).expanduser().resolve()
    for p in os.environ.get("KDECK_ALLOWED_ROOTS", "/home/kojima/work/url2ai").split(",")
    if p.strip()
]
REMOTE_PROJECT_NAMES = [
    "url2ai",
    "vwork",
    "aixec",
    "horizon",
    "buzblogger",
    "rqdb4ai",
    "kdeck",
    "kmail",
    "kurage",
    "swork",
    "airadio-scripted-mv",
    "bittensorman.xyz",
]


def project_folders_under(base: str, names: list[str] | None = None) -> list[str]:
    clean_base = base.rstrip("/")
    return [f"{clean_base}/{name}" for name in (names or REMOTE_PROJECT_NAMES)]

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
    local_cwd: str = "/home/kojima/work/kdeck"
    thread_id: str = ""
    model: str = ""
    remote_llm_backend: str = ""
    remote_model: str = ""
    execution_mode: str = DEFAULT_EXECUTION_MODE
    target_agent: str = "local"


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
CHAT_PROCESSES: dict[str, subprocess.Popen[str]] = {}
SWARMCLAW_GATEWAY_CACHE: dict[str, Any] = {"expires": 0.0, "ids": set()}

DEFAULT_AGENTS: list[dict[str, Any]] = [
    {
        "id": "local",
        "label": "local",
        "role": "kdeck local Codex",
        "host": "192.168.0.3",
        "kind": "local",
        "gateway_id": "",
        "allowed_roots": [],
        "folder_base": "/home/kojima/work",
        "project_folders": [],
        "llm_backends": ["codex-cli"],
        "default_llm_backend": "codex-cli",
        "default_model": CODEX_MODEL,
        "backend_default_models": {"codex-cli": CODEX_MODEL},
    },
    {
        "id": "hermes-192-168-0-2",
        "label": "Hermes scheduler",
        "role": "Hermesジョブ、enqueue、スケジュール確認",
        "host": "192.168.0.2",
        "kind": "swarmclaw",
        "gateway_id": "openclaw-192-168-0-2",
        "folder_base": "/home/kojima/exdirect",
        "project_folders": project_folders_under("/home/kojima/exdirect"),
        "llm_backends": ["codex-cli", "claude-cli"],
        "default_llm_backend": "codex-cli",
        "default_model": CODEX_MODEL,
        "backend_default_models": {
            "codex-cli": CODEX_MODEL,
            "claude-cli": os.environ.get("KDECK_REMOTE_CLAUDE_MODEL", "claude-sonnet-4-6"),
        },
    },
    {
        "id": "aixec-api-192-168-0-14",
        "label": "AIxEC API server",
        "role": "AIxEC API、登録API、dashboard report確認",
        "host": "192.168.0.14",
        "kind": "swarmclaw",
        "gateway_id": "openclaw-192-168-0-14",
        "folder_base": "/home/kojima/bittensorman/aidexx",
        "project_folders": project_folders_under("/home/kojima/bittensorman/aidexx", [
            "aixec",
            "url2ai",
            "horizon",
            "buzblogger",
            "vwork",
            "kurage",
            "kdeck",
        ]),
        "llm_backends": ["codex-cli", "claude-cli", "ollama"],
        "default_llm_backend": "codex-cli",
        "default_model": CODEX_MODEL,
        "backend_default_models": REMOTE_BACKEND_DEFAULT_MODELS,
    },
    {
        "id": "hyperframes-192-168-0-11",
        "label": "Hyperframes video",
        "role": "Hyperframes、Kurage Horizon動画生成、YouTube投稿確認",
        "host": "192.168.0.11",
        "kind": "swarmclaw",
        "gateway_id": "openclaw-192-168-0-11",
        "folder_base": "/home/kojima/exdirect",
        "project_folders": project_folders_under("/home/kojima/exdirect", [
            "horizon",
            "airadio-scripted-mv",
            "kurage",
            "vwork",
            "aixec",
            "url2ai",
        ]),
        "llm_backends": ["codex-cli", "claude-cli"],
        "default_llm_backend": "codex-cli",
        "default_model": CODEX_MODEL,
        "backend_default_models": {
            "codex-cli": CODEX_MODEL,
            "claude-cli": os.environ.get("KDECK_REMOTE_CLAUDE_MODEL", "claude-sonnet-4-6"),
        },
    },
]


def load_agents() -> list[dict[str, Any]]:
    raw = os.environ.get("KDECK_AGENTS_JSON", "").strip()
    if not raw:
        return DEFAULT_AGENTS
    try:
        loaded = json.loads(raw)
    except json.JSONDecodeError:
        return DEFAULT_AGENTS
    if not isinstance(loaded, list):
        return DEFAULT_AGENTS
    agents: list[dict[str, Any]] = []
    for item in loaded:
        if not isinstance(item, dict):
            continue
        agent_id = str(item.get("id") or "").strip()
        if not agent_id:
            continue
        agents.append({
            "id": agent_id,
            "label": str(item.get("label") or agent_id),
            "role": str(item.get("role") or ""),
            "host": str(item.get("host") or ""),
            "kind": str(item.get("kind") or "swarmclaw"),
            "gateway_id": str(item.get("gateway_id") or ""),
            "folder_base": str(item.get("folder_base") or "").rstrip("/"),
            "project_folders": [
                str(p).strip()
                for p in item.get("project_folders", [])
                if str(p).strip()
            ] if isinstance(item.get("project_folders"), list) else [],
            "llm_backends": [
                str(p).strip()
                for p in item.get("llm_backends", [])
                if str(p).strip()
            ] if isinstance(item.get("llm_backends"), list) else ["codex-cli", "claude-cli", "ollama"],
            "default_llm_backend": str(item.get("default_llm_backend") or "codex-cli"),
            "default_model": str(item.get("default_model") or CODEX_MODEL),
            "backend_default_models": item.get("backend_default_models") if isinstance(item.get("backend_default_models"), dict) else REMOTE_BACKEND_DEFAULT_MODELS,
            "allowed_roots": [
                str(p).strip()
                for p in item.get("allowed_roots", [])
                if str(p).strip()
            ] if isinstance(item.get("allowed_roots"), list) else [],
        })
    return agents or DEFAULT_AGENTS


AGENTS = load_agents()


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


def safe_task_id(task_id: str) -> str:
    cleaned = re.sub(r"[^a-zA-Z0-9_-]+", "", task_id.strip())
    return cleaned[:100]


def safe_agent_id(agent_id: str) -> str:
    cleaned = re.sub(r"[^a-zA-Z0-9_.-]+", "", agent_id.strip())
    return cleaned[:100] or "local"


def get_agent(agent_id: str) -> dict[str, Any]:
    agent_id = safe_agent_id(agent_id)
    for agent in AGENTS:
        if agent.get("id") == agent_id:
            return agent
    raise HTTPException(status_code=400, detail="target agent is not registered")


def swarmclaw_access_key() -> str:
    for path in (
        Path(SWARMCLAW_HOME) / "platform-api-key.txt",
        Path.cwd() / "platform-api-key.txt",
    ):
        try:
            if path.exists():
                return path.read_text(encoding="utf-8").strip()
        except OSError:
            continue
    return os.environ.get("SWARMCLAW_ACCESS_KEY", os.environ.get("SWARMCLAW_API_KEY", "")).strip()


def swarmclaw_gateway_ids() -> set[str]:
    now = time.time()
    cached_ids = SWARMCLAW_GATEWAY_CACHE.get("ids")
    if now < float(SWARMCLAW_GATEWAY_CACHE.get("expires") or 0) and isinstance(cached_ids, set):
        return cached_ids
    access_key = swarmclaw_access_key()
    if not access_key:
        return set()
    request = urllib.request.Request(
        SWARMCLAW_BASE_URL + "/api/gateways",
        headers={"x-access-key": access_key, "Accept": "application/json"},
        method="GET",
    )
    try:
        with urllib.request.urlopen(request, timeout=3) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except (OSError, urllib.error.URLError, json.JSONDecodeError):
        SWARMCLAW_GATEWAY_CACHE.update({"expires": now + 10, "ids": set()})
        return set()
    ids = {str(item.get("id") or "") for item in payload if isinstance(item, dict)}
    ids.discard("")
    SWARMCLAW_GATEWAY_CACHE.update({"expires": now + 30, "ids": ids})
    return ids


def agent_public(agent: dict[str, Any]) -> dict[str, Any]:
    kind = agent.get("kind") or ""
    gateway_id = str(agent.get("gateway_id") or "")
    folder_base = str(agent.get("folder_base") or "").rstrip("/")
    project_folders = [str(p) for p in ALLOWED_ROOTS] if kind == "local" else [
        str(p)
        for p in agent.get("project_folders", [])
        if str(p).strip()
    ]
    if kind != "local" and not project_folders and folder_base:
        project_folders = project_folders_under(folder_base)
    allowed_roots = project_folders or [str(p) for p in ALLOWED_ROOTS]
    return {
        "id": agent.get("id") or "",
        "label": agent.get("label") or agent.get("id") or "",
        "role": agent.get("role") or "",
        "host": agent.get("host") or "",
        "kind": kind,
        "gateway_id": gateway_id,
        "folder_base": folder_base,
        "project_folders": project_folders,
        "allowed_roots": allowed_roots,
        "llm_backends": agent.get("llm_backends") or ["codex-cli"],
        "default_llm_backend": agent.get("default_llm_backend") or "codex-cli",
        "default_model": agent.get("default_model") or CODEX_MODEL,
        "backend_default_models": agent.get("backend_default_models") or {},
        "configured": bool(kind == "local" or (gateway_id and gateway_id in swarmclaw_gateway_ids())),
    }


def thread_path(thread_id: str) -> Path:
    return CHAT_DIR / f"{thread_id}.json"


def task_path(task_id: str) -> Path:
    return TASK_DIR / f"{task_id}.json"


def memory_path(task_id: str) -> Path:
    return MEMORY_DIR / f"{task_id}.json"


def thread_title(messages: list[dict[str, str]]) -> str:
    for message in messages:
        if message.get("role") == "user":
            title = re.sub(r"\s+", " ", message.get("content", "")).strip()
            return title[:52] + ("..." if len(title) > 52 else "")
    return "New chat"


def history_transcript(messages: list[dict[str, str]]) -> str:
    selected: list[str] = []
    used_chars = 0
    for message in reversed(messages[-CHAT_PROMPT_MESSAGE_LIMIT:]):
        role = message.get("role", "").upper()
        content = message.get("content", "")
        if role not in {"USER", "ASSISTANT"} or not content:
            continue
        entry = f"{role}:\n{content}"
        entry_chars = len(entry)
        if selected and used_chars + entry_chars > CHAT_PROMPT_CHAR_LIMIT:
            break
        selected.append(entry)
        used_chars += entry_chars
    return "\n\n".join(reversed(selected))


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
            "local_cwd": str(payload.get("local_cwd") or ""),
            "model": str(payload.get("model") or ""),
            "remote_llm_backend": str(payload.get("remote_llm_backend") or ""),
            "remote_model": str(payload.get("remote_model") or ""),
            "execution_mode": str(payload.get("execution_mode") or DEFAULT_EXECUTION_MODE),
            "target_agent": str(payload.get("target_agent") or "local"),
            "created": int(payload.get("created") or 0),
            "updated": int(payload.get("updated") or 0),
        }
    except Exception:
        CHAT_THREADS[thread_id] = []
    return CHAT_THREADS[thread_id]


def save_thread(thread_id: str, cwd: str, model: str, target_agent: str = "local", local_cwd: str = "", remote_llm_backend: str = "", remote_model: str = "") -> None:
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
        "local_cwd": local_cwd or str(meta.get("local_cwd") or ""),
        "model": model,
        "remote_llm_backend": remote_llm_backend or str(meta.get("remote_llm_backend") or ""),
        "remote_model": remote_model or str(meta.get("remote_model") or ""),
        "execution_mode": str(meta.get("execution_mode") or DEFAULT_EXECUTION_MODE),
        "target_agent": target_agent,
        "created": created,
        "updated": now,
        "messages": messages[-CHAT_SAVE_MESSAGE_LIMIT:],
    }
    thread_path(thread_id).write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    CHAT_META[thread_id] = {k: payload[k] for k in ("id", "title", "cwd", "local_cwd", "model", "remote_llm_backend", "remote_model", "execution_mode", "target_agent", "created", "updated")}


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
                "local_cwd": str(payload.get("local_cwd") or ""),
                "model": str(payload.get("model") or ""),
                "remote_llm_backend": str(payload.get("remote_llm_backend") or ""),
                "remote_model": str(payload.get("remote_model") or ""),
                "execution_mode": str(payload.get("execution_mode") or DEFAULT_EXECUTION_MODE),
                "target_agent": str(payload.get("target_agent") or "local"),
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


def normalize_execution_mode(mode: str) -> str:
    mode = (mode or "").strip()
    return mode if mode in CODEX_EXECUTION_MODES else DEFAULT_EXECUTION_MODE


def execution_mode_instruction(execution_mode: str) -> str:
    if execution_mode == "chat-only":
        return (
            "Execution mode: chat-only.\n"
            "Discuss only. Do not run shell commands, do not call tools, do not edit files, "
            "do not access external services, and do not claim you changed anything. "
            "If the user asks for implementation, explain what you would do and ask them to switch execution mode.\n\n"
        )
    if execution_mode == "full-access":
        return (
            "Execution mode: full-access.\n"
            "Before taking any action, start your response with a short acknowledgement in Japanese such as "
            "'了解しました。これから実行します。' Then proceed with the requested work.\n\n"
        )
    return (
        "Execution mode: confirm.\n"
        "Before taking any action, start your response with a short acknowledgement in Japanese such as "
        "'了解しました。確認しながら進めます。' Then proceed within the selected sandbox.\n\n"
    )


def save_agent_task(task: dict[str, Any]) -> None:
    TASK_DIR.mkdir(parents=True, exist_ok=True)
    task_id = safe_task_id(str(task.get("job_id") or task.get("task_id") or ""))
    if not task_id:
        return
    task_path(task_id).write_text(json.dumps(task, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def summarize_for_memory(text: str, limit: int = 1200) -> str:
    text = re.sub(r"\s+", " ", text or "").strip()
    if len(text) <= limit:
        return text
    return text[:limit] + "..."


def save_shared_memory(task: dict[str, Any], result_text: str) -> None:
    MEMORY_DIR.mkdir(parents=True, exist_ok=True)
    task_id = safe_task_id(str(task.get("job_id") or task.get("task_id") or ""))
    if not task_id:
        return
    record = {
        "task_id": task_id,
        "target_agent": task.get("target_agent") or "local",
        "role": task.get("agent_role") or "",
        "repo": task.get("cwd") or "",
        "status": task.get("status") or "",
        "summary": summarize_for_memory(result_text),
        "created": task.get("created") or 0,
        "finished": task.get("finished") or 0,
    }
    memory_path(task_id).write_text(json.dumps(record, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def list_agent_tasks() -> list[dict[str, Any]]:
    TASK_DIR.mkdir(parents=True, exist_ok=True)
    items: list[dict[str, Any]] = []
    for path in TASK_DIR.glob("*.json"):
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(payload, dict):
                items.append(payload)
        except Exception:
            continue
    return sorted(items, key=lambda item: item.get("created") or 0, reverse=True)[:100]


def list_shared_memory() -> list[dict[str, Any]]:
    MEMORY_DIR.mkdir(parents=True, exist_ok=True)
    items: list[dict[str, Any]] = []
    for path in MEMORY_DIR.glob("*.json"):
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(payload, dict):
                items.append(payload)
        except Exception:
            continue
    return sorted(items, key=lambda item: item.get("finished") or item.get("created") or 0, reverse=True)[:100]


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
    return {
        "ok": True,
        "allowed_roots": [str(p) for p in ALLOWED_ROOTS],
        "codex_cmd": CODEX_CMD,
        "codex_model": CODEX_MODEL,
        "codex_sandbox": CODEX_SANDBOX,
        "execution_modes": CODEX_EXECUTION_MODES,
        "default_execution_mode": DEFAULT_EXECUTION_MODE,
        "agents": [agent_public(agent) for agent in AGENTS],
        "backend": "pty",
    }


@app.get("/api/agents", dependencies=[Depends(require_auth)])
def agents() -> dict[str, Any]:
    return {"ok": True, "agents": [agent_public(agent) for agent in AGENTS]}


@app.get("/api/agent_tasks", dependencies=[Depends(require_auth)])
def agent_tasks() -> dict[str, Any]:
    return {"ok": True, "tasks": list_agent_tasks()}


@app.get("/api/shared_memory", dependencies=[Depends(require_auth)])
def shared_memory() -> dict[str, Any]:
    return {"ok": True, "items": list_shared_memory()}


@app.get("/api/controller/status", dependencies=[Depends(require_auth)])
def controller_status() -> dict[str, Any]:
    return controller.status()


@app.post("/api/controller/tick", dependencies=[Depends(require_auth)])
def controller_tick() -> dict[str, Any]:
    script = Path(__file__).resolve().parents[1] / "scripts" / "hermes_commander_once.sh"
    if not script.exists():
        raise HTTPException(status_code=500, detail="hermes commander script not found")
    proc = subprocess.run(
        [str(script)],
        cwd=str(Path(__file__).resolve().parents[1]),
        text=True,
        capture_output=True,
        timeout=600,
        check=False,
    )
    return {
        "ok": proc.returncode == 0,
        "returncode": proc.returncode,
        "stdout_tail": proc.stdout[-4000:],
        "stderr_tail": proc.stderr[-4000:],
        "status": controller.status(),
    }


@app.post("/api/controller/goals/{goal_name}/hold", dependencies=[Depends(require_auth)])
def controller_hold_goal(goal_name: str) -> dict[str, Any]:
    try:
        return controller.set_goal_status(goal_name, "hold")
    except KeyError:
        raise HTTPException(status_code=404, detail="goal not found")


@app.post("/api/controller/goals/{goal_name}/resume", dependencies=[Depends(require_auth)])
def controller_resume_goal(goal_name: str) -> dict[str, Any]:
    try:
        return controller.set_goal_status(goal_name, "waiting")
    except KeyError:
        raise HTTPException(status_code=404, detail="goal not found")


def run_codex_exec(cwd: Path, model: str, prompt: str, job_id: str = "", execution_mode: str = DEFAULT_EXECUTION_MODE) -> dict[str, Any]:
    execution_mode = normalize_execution_mode(execution_mode)
    sandbox = CODEX_EXECUTION_MODES[execution_mode]["sandbox"]
    cmd = [
        CODEX_CMD,
        "exec",
        "--json",
        "-m",
        model,
        "--cd",
        str(cwd),
        "--sandbox",
        sandbox,
        "-",
    ]
    proc = subprocess.Popen(
        cmd,
        text=True,
        cwd=str(cwd),
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        stdin=subprocess.PIPE,
        start_new_session=True,
    )
    if job_id:
        CHAT_PROCESSES[job_id] = proc
    try:
        stdout, stderr = proc.communicate(input=prompt, timeout=900)
    except subprocess.TimeoutExpired:
        try:
            os.killpg(proc.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        stdout, stderr = proc.communicate()
        return {
            "returncode": 124,
            "text": "Codex CLI timed out after 900 seconds.",
            "stderr_tail": (stderr or "")[-4000:],
            "events": [],
        }
    finally:
        if job_id:
            CHAT_PROCESSES.pop(job_id, None)
    final_text = ""
    events: list[dict[str, Any]] = []
    for line in stdout.splitlines():
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
        final_text = (stderr or stdout or f"codex exited with {proc.returncode}").strip()
    return {
        "returncode": proc.returncode,
        "text": final_text,
        "stderr_tail": stderr[-4000:],
        "events": events[-20:],
        "execution_mode": execution_mode,
        "sandbox": sandbox,
    }


def remote_backend_model(backend: str, requested: str, agent: dict[str, Any]) -> str:
    requested = requested.strip()
    if requested:
        return requested
    defaults = agent.get("backend_default_models")
    if isinstance(defaults, dict):
        model = str(defaults.get(backend) or "").strip()
        if model:
            return model
    return REMOTE_BACKEND_DEFAULT_MODELS.get(backend, CODEX_MODEL)


def remote_executable_probe(candidates: list[str]) -> str:
    quoted = " ".join(shlex.quote(candidate) for candidate in candidates)
    return (
        "for candidate in " + quoted + "; do "
        "expanded=$(eval printf '%s' \"$candidate\"); "
        "if command -v \"$expanded\" >/dev/null 2>&1; then command -v \"$expanded\"; exit 0; fi; "
        "if [ -x \"$expanded\" ]; then printf '%s\\n' \"$expanded\"; exit 0; fi; "
        "done; exit 127"
    )


def ssh_base_command(agent: dict[str, Any]) -> list[str]:
    host = str(agent.get("host") or "").strip()
    if not host:
        raise RuntimeError(f"{agent.get('id')} has no host configured")
    cmd = [
        "ssh",
        "-i",
        REMOTE_SSH_KEY,
        "-p",
        str(REMOTE_SSH_PORT),
        "-o",
        "BatchMode=yes",
        "-o",
        "ConnectTimeout=10",
        "-o",
        "StrictHostKeyChecking=no",
        f"{REMOTE_SSH_USER}@{host}",
    ]
    return cmd


def run_remote_ssh_command(agent: dict[str, Any], remote_script: str, prompt: str, timeout: int, job_id: str = "") -> tuple[int, str, str]:
    cmd = ssh_base_command(agent) + ["bash", "-lc", remote_script]
    proc = subprocess.Popen(
        cmd,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        stdin=subprocess.PIPE,
        start_new_session=True,
    )
    if job_id:
        CHAT_PROCESSES[job_id] = proc
    try:
        stdout, stderr = proc.communicate(prompt, timeout=timeout)
    except subprocess.TimeoutExpired:
        try:
            os.killpg(proc.pid, signal.SIGTERM)
        except ProcessLookupError:
            pass
        stdout, stderr = proc.communicate(timeout=10)
        return 124, stdout, (stderr or "") + f"\nremote command timed out after {timeout} seconds"
    finally:
        if job_id:
            CHAT_PROCESSES.pop(job_id, None)
    return proc.returncode, stdout or "", stderr or ""


def parse_codex_json_output(stdout: str, stderr: str, returncode: int) -> tuple[str, list[dict[str, Any]]]:
    final_text = ""
    events: list[dict[str, Any]] = []
    for line in stdout.splitlines():
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
    if returncode != 0 and not final_text:
        final_text = (stderr or stdout or f"remote codex exited with {returncode}").strip()
    return final_text, events[-20:]


def openclaw_model_for_backend(backend: str, model: str) -> str:
    model = model.strip()
    if backend == "codex-cli":
        return model if model.startswith("openai/") else f"openai/{model or CODEX_MODEL}"
    if backend == "claude-cli":
        if model.startswith("claude-cli/"):
            return model
        return f"claude-cli/{model or REMOTE_BACKEND_DEFAULT_MODELS['claude-cli']}"
    if backend == "ollama":
        return model if model.startswith("ollama/") else f"ollama/{model or REMOTE_BACKEND_DEFAULT_MODELS['ollama']}"
    return model


def gateway_ws_url(agent: dict[str, Any]) -> str:
    configured = str(agent.get("ws_url") or agent.get("gateway_ws_url") or "").strip()
    if configured:
        return configured
    host = str(agent.get("host") or "").strip()
    if not host:
        raise RuntimeError(f"{agent.get('id')} has no host configured")
    return f"ws://{host}:18789"


def gateway_token(gateway_id: str) -> str:
    if not gateway_id:
        return ""
    env_name = "KDECK_" + re.sub(r"[^A-Za-z0-9]+", "_", gateway_id).upper() + "_TOKEN"
    token = os.environ.get(env_name, "").strip()
    if token:
        return token
    token_path = Path(SWARMCLAW_HOME) / f"{gateway_id}.token"
    try:
        if token_path.exists():
            return token_path.read_text(encoding="utf-8").strip()
    except OSError:
        return ""
    return ""


def parse_openclaw_json(stdout: str) -> dict[str, Any]:
    stdout = stdout.strip()
    if not stdout:
        return {}
    try:
        return json.loads(stdout)
    except json.JSONDecodeError:
        start = stdout.find("{")
        end = stdout.rfind("}")
        if start >= 0 and end > start:
            return json.loads(stdout[start:end + 1])
        raise


def run_remote_openclaw_agent(agent: dict[str, Any], cwd: str, backend: str, model: str, prompt: str, thread_id: str, job_id: str) -> dict[str, Any]:
    gateway_id = str(agent.get("gateway_id") or "").strip()
    token = gateway_token(gateway_id)
    if not token:
        return {
            "returncode": 2,
            "text": f"{gateway_id} token is not configured.",
            "stderr_tail": "",
            "events": [],
        }
    model_ref = openclaw_model_for_backend(backend, model)
    ws_url = gateway_ws_url(agent)
    session_suffix = re.sub(r"[^a-zA-Z0-9_-]+", "-", f"kdeck-{thread_id}-{job_id}")[:120]
    remote_prompt = (
        "Kurage Agent Deckからの委任タスクです。\n"
        f"対象サーバ: {agent.get('host') or ''}\n"
        f"対象ロール: {agent.get('role') or ''}\n"
        f"選択されたリモート作業フォルダ: {cwd}\n"
        "作業や確認が必要な場合は、まず上記フォルダを対象にしてください。\n\n"
        + prompt
    )
    config = {
        "gateway": {
            "mode": "remote",
            "remote": {
                "transport": "direct",
                "url": ws_url,
                "token": token,
            },
        }
    }
    tmp_path = ""
    proc: subprocess.Popen[str] | None = None
    try:
        with tempfile.NamedTemporaryFile("w", encoding="utf-8", suffix=".openclaw.json", delete=False) as tmp:
            json.dump(config, tmp)
            tmp.write("\n")
            tmp_path = tmp.name
        env = os.environ.copy()
        openclaw_dir = str(Path(OPENCLAW_CMD).expanduser().parent)
        env["PATH"] = f"{openclaw_dir}:" + env.get("PATH", "")
        env["OPENCLAW_CONFIG_PATH"] = tmp_path
        cmd = [
            OPENCLAW_CMD,
            "agent",
            "--agent",
            "main",
            "--session-key",
            f"agent:main:{session_suffix}",
            "--message",
            remote_prompt,
            "--model",
            model_ref,
            "--timeout",
            "900",
            "--json",
        ]
        proc = subprocess.Popen(
            cmd,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            start_new_session=True,
            env=env,
        )
        if job_id:
            CHAT_PROCESSES[job_id] = proc
        try:
            stdout, stderr = proc.communicate(timeout=930)
        except subprocess.TimeoutExpired:
            try:
                os.killpg(proc.pid, signal.SIGTERM)
            except ProcessLookupError:
                pass
            stdout, stderr = proc.communicate(timeout=10)
            return {
                "returncode": 124,
                "text": "OpenClaw remote agent timed out after 900 seconds.",
                "stderr_tail": (stderr or "")[-4000:],
                "events": [],
            }
    finally:
        if job_id:
            CHAT_PROCESSES.pop(job_id, None)
        if tmp_path:
            try:
                Path(tmp_path).unlink()
            except OSError:
                pass
    stdout = stdout or ""
    stderr = stderr or ""
    payload: dict[str, Any] = {}
    text = ""
    events: list[dict[str, Any]] = []
    if proc and proc.returncode == 0:
        try:
            payload = parse_openclaw_json(stdout)
            result = payload.get("result") if isinstance(payload.get("result"), dict) else {}
            for item in result.get("payloads", []) if isinstance(result.get("payloads"), list) else []:
                if isinstance(item, dict) and item.get("text"):
                    text = str(item.get("text"))
                    break
            if not text:
                meta = result.get("meta") if isinstance(result.get("meta"), dict) else {}
                text = str(meta.get("finalAssistantVisibleText") or meta.get("finalAssistantRawText") or "")
            events = [payload]
        except Exception:
            text = stdout.strip()
    if proc and proc.returncode != 0 and not text:
        text = (stderr or stdout or f"openclaw agent exited with {proc.returncode}").strip()
    return {
        "returncode": proc.returncode if proc else 1,
        "text": text,
        "stderr_tail": stderr[-4000:],
        "events": events[-5:],
        "openclaw": payload,
        "model_ref": model_ref,
        "gateway_url": ws_url,
    }


def run_remote_codex(agent: dict[str, Any], cwd: str, model: str, prompt: str, job_id: str, execution_mode: str) -> dict[str, Any]:
    sandbox = CODEX_EXECUTION_MODES[normalize_execution_mode(execution_mode)]["sandbox"]
    remote_script = (
        "set -e; "
        f"bin=$({remote_executable_probe(REMOTE_CODEX_CANDIDATES)}); "
        f"cd {shlex.quote(cwd)}; "
        "\"$bin\" exec --json "
        f"-m {shlex.quote(model)} "
        f"--sandbox {shlex.quote(sandbox)} -"
    )
    returncode, stdout, stderr = run_remote_ssh_command(agent, remote_script, prompt, 900, job_id)
    text, events = parse_codex_json_output(stdout, stderr, returncode)
    return {
        "returncode": returncode,
        "text": text,
        "stderr_tail": stderr[-4000:],
        "events": events,
        "sandbox": sandbox,
    }


def run_remote_claude(agent: dict[str, Any], cwd: str, model: str, prompt: str, job_id: str, execution_mode: str) -> dict[str, Any]:
    permission_mode = "bypassPermissions" if normalize_execution_mode(execution_mode) == "full-access" else "default"
    remote_script = (
        "set -e; "
        f"bin=$({remote_executable_probe(REMOTE_CLAUDE_CANDIDATES)}); "
        f"cd {shlex.quote(cwd)}; "
        "\"$bin\" -p "
        f"{shlex.quote(prompt)} "
        f"--model {shlex.quote(model)} "
        "--output-format text "
        "--tools '' "
        f"--permission-mode {shlex.quote(permission_mode)}"
    )
    returncode, stdout, stderr = run_remote_ssh_command(agent, remote_script, "", 900, job_id)
    text = clean_claude_text(stdout.strip()) or stderr.strip()
    return {
        "returncode": returncode,
        "text": text,
        "stderr_tail": stderr[-4000:],
        "events": [],
        "sandbox": permission_mode,
    }


def clean_claude_text(text: str) -> str:
    if not text.startswith("BASH="):
        return text
    lines = text.splitlines()
    while lines and re.match(r"^[A-Za-z_][A-Za-z0-9_]*=", lines[0]):
        lines.pop(0)
    return "\n".join(lines).strip() or text


def run_remote_ollama(agent: dict[str, Any], cwd: str, model: str, prompt: str, job_id: str) -> dict[str, Any]:
    remote_script = (
        "set -e; "
        f"bin=$({remote_executable_probe(REMOTE_OLLAMA_CANDIDATES)}); "
        f"cd {shlex.quote(cwd)}; "
        "\"$bin\" run " + shlex.quote(model)
    )
    returncode, stdout, stderr = run_remote_ssh_command(agent, remote_script, prompt, 300, job_id)
    text = stdout.strip() or stderr.strip()
    return {
        "returncode": returncode,
        "text": text,
        "stderr_tail": stderr[-4000:],
        "events": [],
        "sandbox": "ollama",
    }


def run_remote_agent(agent: dict[str, Any], req: ChatRequest, thread_id: str, job_id: str) -> dict[str, Any]:
    gateway_id = str(agent.get("gateway_id") or "").strip()
    remote_llm_backend = req.remote_llm_backend.strip() or str(agent.get("default_llm_backend") or "codex-cli")
    remote_model = remote_backend_model(remote_llm_backend, req.remote_model.strip(), agent)
    if not gateway_id:
        return {
            "returncode": 2,
            "text": f"{agent.get('id')} is not configured. Set a SwarmClaw gateway_id before sending tasks.",
            "stderr_tail": "",
            "remote_job": {},
        }
    if remote_llm_backend in {"codex-cli", "claude-cli", "ollama"}:
        result = run_remote_openclaw_agent(agent, req.cwd, remote_llm_backend, remote_model, req.prompt, thread_id, job_id)
    else:
        result = {
            "returncode": 2,
            "text": f"Unsupported remote LLM backend: {remote_llm_backend}",
            "stderr_tail": "",
            "events": [],
        }
    result["remote_job"] = {
        "control_plane": "openclaw",
        "swarmclaw_base_url": SWARMCLAW_BASE_URL,
        "gateway_id": gateway_id,
        "gateway_url": result.get("gateway_url") or gateway_ws_url(agent),
        "host": agent.get("host") or "",
        "cwd": req.cwd,
        "llm_backend": remote_llm_backend,
        "model": result.get("model_ref") or openclaw_model_for_backend(remote_llm_backend, remote_model),
    }
    return result


@app.post("/api/chat", dependencies=[Depends(require_auth)])
def chat(req: ChatRequest) -> dict[str, Any]:
    target_agent = safe_agent_id(req.target_agent)
    agent = get_agent(target_agent)
    cwd = validate_cwd(req.cwd) if agent.get("kind") == "local" else Path(req.cwd).expanduser()
    model = req.model.strip() or CODEX_MODEL
    remote_llm_backend = req.remote_llm_backend.strip()
    remote_model = req.remote_model.strip()
    execution_mode = normalize_execution_mode(req.execution_mode)
    sandbox = CODEX_EXECUTION_MODES[execution_mode]["sandbox"]
    thread_id = safe_thread_id(req.thread_id) or f"chat-{uuid.uuid4().hex[:8]}"
    job_id = f"chatjob-{uuid.uuid4().hex[:10]}"
    CHAT_JOBS[job_id] = {
        "ok": True,
        "job_id": job_id,
        "thread_id": thread_id,
        "status": "running",
        "model": model,
        "remote_llm_backend": remote_llm_backend,
        "remote_model": remote_model,
        "execution_mode": execution_mode,
        "sandbox": sandbox,
        "target_agent": target_agent,
        "agent_role": agent.get("role") or "",
        "cwd": str(cwd),
        "local_cwd": req.local_cwd,
        "message": "",
        "error": "",
        "created": int(time.time()),
        "finished": 0,
    }

    def worker() -> None:
        try:
            result = run_chat_turn(cwd, model, thread_id, req.prompt, job_id, execution_mode, target_agent, req.local_cwd, remote_llm_backend, remote_model)
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
        finally:
            save_agent_task(CHAT_JOBS[job_id])
            save_shared_memory(CHAT_JOBS[job_id], str(CHAT_JOBS[job_id].get("message") or CHAT_JOBS[job_id].get("error") or ""))

    threading.Thread(target=worker, daemon=True).start()
    save_agent_task(CHAT_JOBS[job_id])
    return CHAT_JOBS[job_id]


def run_chat_turn(cwd: Path, model: str, thread_id: str, user_prompt: str, job_id: str = "", execution_mode: str = DEFAULT_EXECUTION_MODE, target_agent: str = "local", local_cwd: str = "", remote_llm_backend: str = "", remote_model: str = "") -> dict[str, Any]:
    execution_mode = normalize_execution_mode(execution_mode)
    sandbox = CODEX_EXECUTION_MODES[execution_mode]["sandbox"]
    target_agent = safe_agent_id(target_agent)
    agent = get_agent(target_agent)
    history = load_thread(thread_id)
    transcript = history_transcript(history)
    agent_context = (
        f"Target agent: {agent.get('id')}\n"
        f"Agent role: {agent.get('role') or 'local Codex'}\n"
        f"Agent host: {agent.get('host') or 'local'}\n\n"
    )
    prompt = (
        "You are Codex in Kurage Agent Deck. Answer in Japanese unless the user asks otherwise.\n"
        "Continue the conversation below and act on the selected workspace when needed.\n"
        "The conversation block is persisted chat history from this deck. Use it as context when answering.\n\n"
        + execution_mode_instruction(execution_mode)
        + agent_context
        + (transcript + "\n\n" if transcript else "")
        + "USER:\n"
        + user_prompt
    )
    history.append({"role": "user", "content": user_prompt})
    CHAT_META.setdefault(thread_id, {})["execution_mode"] = execution_mode
    CHAT_META.setdefault(thread_id, {})["target_agent"] = target_agent
    CHAT_META.setdefault(thread_id, {})["local_cwd"] = local_cwd
    CHAT_META[thread_id]["local_cwd"] = local_cwd
    CHAT_META[thread_id]["remote_llm_backend"] = remote_llm_backend
    CHAT_META[thread_id]["remote_model"] = remote_model
    save_thread(thread_id, str(cwd), model, target_agent, local_cwd, remote_llm_backend, remote_model)
    if agent.get("kind") == "local":
        result = run_codex_exec(cwd, model, prompt, job_id, execution_mode)
    else:
        remote_req = ChatRequest(
            prompt=prompt,
            cwd=str(cwd),
            local_cwd=local_cwd,
            thread_id=thread_id,
            model=model,
            remote_llm_backend=remote_llm_backend,
            remote_model=remote_model,
            execution_mode=execution_mode,
            target_agent=target_agent,
        )
        result = run_remote_agent(agent, remote_req, thread_id, job_id)
    assistant_text = result["text"] or "(no response)"
    history.append({"role": "assistant", "content": assistant_text})
    save_thread(thread_id, str(cwd), model, target_agent, local_cwd, remote_llm_backend, remote_model)
    return {
        "ok": result["returncode"] == 0,
        "thread_id": thread_id,
        "model": model,
        "remote_llm_backend": remote_llm_backend,
        "remote_model": remote_model,
        "execution_mode": execution_mode,
        "sandbox": sandbox,
        "target_agent": target_agent,
        "agent_role": agent.get("role") or "",
        "cwd": str(cwd),
        "local_cwd": local_cwd,
        "message": assistant_text,
        "stderr_tail": result["stderr_tail"],
        "remote_job": result.get("remote_job") or {},
    }


@app.get("/api/chat/{job_id}", dependencies=[Depends(require_auth)])
def chat_job(job_id: str) -> dict[str, Any]:
    job = CHAT_JOBS.get(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="chat job not found")
    if job.get("status") == "running":
        job["elapsed"] = int(time.time()) - int(job.get("created") or time.time())
    return job


@app.post("/api/chat/{job_id}/cancel", dependencies=[Depends(require_auth)])
def cancel_chat_job(job_id: str) -> dict[str, Any]:
    job = CHAT_JOBS.get(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="chat job not found")
    proc = CHAT_PROCESSES.get(job_id)
    if proc is not None and proc.poll() is None:
        try:
            os.killpg(proc.pid, signal.SIGTERM)
        except ProcessLookupError:
            pass
    job.update({
        "ok": False,
        "status": "failed",
        "error": "cancelled",
        "finished": int(time.time()),
    })
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
            "local_cwd": meta.get("local_cwd") or "",
            "model": meta.get("model") or "",
            "remote_llm_backend": meta.get("remote_llm_backend") or "",
            "remote_model": meta.get("remote_model") or "",
            "execution_mode": meta.get("execution_mode") or DEFAULT_EXECUTION_MODE,
            "target_agent": meta.get("target_agent") or "local",
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
