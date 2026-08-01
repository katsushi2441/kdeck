from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from app import controller, main


def test_codex_fallback_only_for_availability_errors() -> None:
    assert main.codex_needs_claude_fallback({"returncode": 1, "text": "HTTP 429 rate limit", "stderr_tail": ""})
    assert main.codex_needs_claude_fallback({"returncode": 1, "text": "authentication required", "stderr_tail": ""})
    assert main.codex_needs_claude_fallback({"returncode": 1, "text": "model is not supported when using Codex", "stderr_tail": ""})
    assert not main.codex_needs_claude_fallback({"returncode": 1, "text": "tests failed", "stderr_tail": ""})
    assert not main.codex_needs_claude_fallback({"returncode": 0, "text": "rate limit is documented", "stderr_tail": ""})


def test_local_agent_has_current_backends_and_discovered_projects() -> None:
    agent = main.get_agent("local")
    assert agent["llm_backends"] == ["auto", "codex-cli", "claude-cli"]
    assert main.CODEX_MODEL in agent["backend_models"]["codex-cli"]
    assert "/home/kojima/work/kfreqai" in agent["project_folders"]


def test_controller_database_initialization_is_concurrent_safe(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(controller, "DB_PATH", tmp_path / "controller.sqlite")
    monkeypatch.setattr(controller, "DEFAULT_GOALS", [])
    monkeypatch.setattr(controller, "KGROWTH_IMPROVEMENT_JOBS_PATH", None)
    monkeypatch.setattr(controller, "_DB_INITIALIZED", False)

    with ThreadPoolExecutor(max_workers=12) as pool:
        list(pool.map(lambda _: controller.init_db(), range(48)))

    with controller.connect() as conn:
        assert conn.execute("PRAGMA journal_mode").fetchone()[0].lower() == "wal"
        assert conn.execute("SELECT COUNT(*) FROM goals").fetchone()[0] == 0
