# Kurage Agent Deck (kdeck)

Kurage Agent Deck is a small mobile web console for controlling local coding-agent CLI sessions on this Linux server.

Initial target:

- Project name: Kurage Agent Deck
- Folder: `kdeck`
- API: FastAPI on port `18301`
- Web: `https://kurage.exbridge.jp/kdeck.php`
- Runtime: built-in Python PTY sessions + Codex CLI

## Architecture

```text
Smartphone browser
  -> kurage.exbridge.jp/kdeck.php
  -> PHP server-side proxy with Kurage common X login
  -> http://<linux-server>:18301
  -> FastAPI
  -> PTY sessions
  -> codex CLI
```

The PHP page keeps the API token on the web server side. The browser talks to PHP, not directly to FastAPI.
The MVP stores sessions in API process memory, so active sessions disappear when `kdeck-api` restarts.
Chat threads are saved under `KDECK_DATA_DIR` so the web UI and later Codex turns can reopen and reference recent conversations.
The multi-server PoC adds a `target_agent` selector so kdeck can keep task history for the local Codex runtime and SwarmClaw-managed OpenClaw runtimes.

See [Kurage Agent Deck の技術解説](docs/kurage-agent-deck-technical-overview.md) for a Japanese technical overview.
See [kdeck Multi-Server Agent Plan](docs/multi-server-agent-plan.md) for the 192.168.0.3 / .2 / .14 / .11 agent layout.

## Multi-Server Direction

`192.168.0.3` is the only kdeck/SwarmClaw control server. Other machines should not receive kdeck-specific HTTP gateways or cloned application repositories just for orchestration. They run OpenClaw, and SwarmClaw owns task state, shared memory, gateway lifecycle, and routing.

## Setup

Create `.env` from `.env.sample` and set a strong token.

```bash
cp .env.sample .env
python3 -m venv .venv
. .venv/bin/activate
pip install -r requirements.txt
scripts/run_kdeck.sh
```

For the deployed PHP proxy, copy `web/kdeck_config.sample.php` to
`web/kdeck_config.php` on the web server and set the same `KDECK_TOKEN` used by
the FastAPI server. The real `kdeck_config.php` is intentionally ignored by git.

`KDECK_CODEX_SANDBOX` controls the Codex CLI sandbox mode. Use `danger-full-access`
only on a trusted, login-protected deployment when Codex needs network access for
operations such as `git push`.

The chat UI also has an execution mode selector:

- `confirm`: asks in the browser before starting Codex and runs with `workspace-write`.
- `full-access`: runs immediately with `danger-full-access`.

Set `KDECK_DEFAULT_EXECUTION_MODE=confirm` to keep the safer mode selected by default.

## API

- `GET /healthz`
- `GET /api/sessions`
- `POST /api/sessions`
- `GET /api/sessions/{id}/capture`
- `POST /api/sessions/{id}/send`
- `POST /api/sessions/{id}/interrupt`
- `POST /api/sessions/{id}/terminate`
- `POST /api/chat`
- `GET /api/chat/{job_id}`
- `POST /api/chat/{job_id}/cancel`
- `GET /api/chat_threads`
- `GET /api/chat_threads/{thread_id}`
- `GET /api/agents`
- `GET /api/agent_tasks`
- `GET /api/shared_memory`

## Security

- Bind behind firewall/port-forwarding with HTTPS at the edge.
- Use `KDECK_TOKEN` for all API calls.
- Protect `kdeck.php` with `kurage.exbridge.jp` common X login; it can control local shell sessions.
- Allowed working directories are controlled by `KDECK_ALLOWED_ROOTS`.
- Avoid sudo from mobile sessions.
