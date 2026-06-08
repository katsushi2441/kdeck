# Kurage Agent Deck (kdeck)

Kurage Agent Deck is a mobile web console for controlling coding-agent sessions
from a single browser entry point.

The current implementation has two layers:

- local shell/PTY sessions on the kdeck server for simple direct operations
- multi-server AI agent routing through OpenClaw gateways for remote server work

Initial target:

- Project name: Kurage Agent Deck
- Folder: `kdeck`
- API: FastAPI on port `18301`
- Web: `https://kurage.exbridge.jp/kdeck.php`
- Local runtime: built-in Python PTY sessions
- Remote runtime: OpenClaw gateway + Codex CLI / Claude CLI on each target server

## Architecture

### Web Entry Point

```text
Smartphone browser
  -> kurage.exbridge.jp/kdeck.php
  -> PHP server-side proxy with Kurage common X login
  -> http://<linux-server>:18301
  -> FastAPI
     -> local PTY sessions on 192.168.0.3
     -> remote OpenClaw gateways on .2 / .14 / .11
```

The PHP page keeps the API token on the web server side. The browser talks to PHP, not directly to FastAPI.
The API runs as the user systemd service `kdeck-api.service` on the kdeck integration server.
The local PTY session feature stores active sessions in API process memory, so active PTY sessions disappear when `kdeck-api` restarts.
Chat threads are saved under `KDECK_DATA_DIR` so the web UI and later Codex turns can reopen and reference recent conversations.
The multi-server PoC adds a `target_agent` selector so kdeck can keep task history for the local Codex runtime and SwarmClaw-managed OpenClaw runtimes.

See [Kurage Agent Deck の技術解説](docs/kurage-agent-deck-technical-overview.md) for a Japanese technical overview.
See [kdeck Multi-Server Agent Plan](docs/multi-server-agent-plan.md) for the 192.168.0.3 / .2 / .14 / .11 agent layout.

## Multi-Server Agent Architecture

`192.168.0.3` is the only kdeck integration/control server. The remote servers
do not receive kdeck-specific HTTP gateways. They run OpenClaw gateway processes,
and kdeck routes work to those gateways.

```text
Smartphone
  -> https://kurage.exbridge.jp/kdeck.php
  -> PHP proxy with Kurage common X login
  -> kdeck FastAPI on 192.168.0.3:18301
  -> OpenClaw remote gateway selected by target_agent
     -> 192.168.0.2:18789  Hermes scheduler agent
     -> 192.168.0.14:18789 AIxEC API server agent
     -> 192.168.0.11:18789 Hyperframes video agent
```

### Server Roles

| Server | Role | Project roots used by the agent | Agent backends |
| --- | --- | --- | --- |
| `192.168.0.3` | kdeck integration/control server | `/home/kojima/work/...` | local PTY plus OpenClaw client |
| `192.168.0.2` | Hermes scheduler server | `/home/kojima/exdirect/...` | OpenClaw -> Codex CLI / Claude CLI |
| `192.168.0.14` | AIxEC API server | `/home/kojima/bittensorman/aidexx/...` | OpenClaw -> Codex CLI / Claude CLI |
| `192.168.0.11` | Hyperframes video server | `/home/kojima/exdirect/...` | OpenClaw -> Codex CLI / Claude CLI |

### Agent Selection

kdeck stores both the local working folder and the remote agent target.
When a remote target is selected, the remote folder must be interpreted in that
server's own filesystem, not in the kdeck server filesystem.

Examples:

- `target_agent=hermes-192-168-0-2` uses folders under `/home/kojima/exdirect`
  on `192.168.0.2`.
- `target_agent=aixec-api-192-168-0-14` uses folders under
  `/home/kojima/bittensorman/aidexx` on `192.168.0.14`.
- `target_agent=hyperframes-192-168-0-11` uses folders under
  `/home/kojima/exdirect` on `192.168.0.11`.

The remote LLM selector maps to OpenClaw model names:

- `codex-cli` means OpenClaw model `openai/gpt-5.5` through the Codex app-server harness.
- `claude-cli` means OpenClaw model `claude-cli/claude-sonnet-4-6`.
- Remote agent execution must report `control_plane: openclaw`.

SSH is only used for setup and maintenance. kdeck must not treat direct SSH
execution of `codex`, `claude`, or shell commands as a completed remote agent
task.

### Verified Runtime State

The current deployed shape is:

- `kdeck-api.service` runs on `192.168.0.3` and listens on `0.0.0.0:18301`.
- OpenClaw gateway runs as `openclaw-gateway.service` on `.2`, `.14`, and `.11`.
- Each OpenClaw gateway listens on LAN port `18789` with token authentication.
- kdeck API has verified successful `Return OK only` calls through OpenClaw to:
  - `.2` with `codex-cli`
  - `.2` with `claude-cli`
  - `.14` with `codex-cli`
  - `.14` with `claude-cli`
  - `.11` with `codex-cli`
  - `.11` with `claude-cli`

## Diagram Prompt

Use this block when asking ChatGPT or another diagramming assistant to create
an architecture diagram:

```text
Create a system architecture diagram for "Kurage Agent Deck (kdeck)".

Main idea:
kdeck is a mobile browser UI and FastAPI control server on 192.168.0.3.
It lets a user route coding-agent tasks to multiple LAN servers.

Entry path:
1. Smartphone browser opens https://kurage.exbridge.jp/kdeck.php.
2. kdeck.php is protected by Kurage common X login.
3. kdeck.php acts as a server-side PHP proxy and keeps the API token away from the browser.
4. The PHP proxy calls kdeck FastAPI on 192.168.0.3:18301.

Control server:
- 192.168.0.3 is the kdeck integration/control server.
- It runs kdeck-api.service.
- It stores chat history, target_agent, local_cwd, remote cwd, selected backend, task status, and result summaries.
- It does not directly SSH into remote servers for normal task execution.

Remote agent execution:
- Remote work goes through OpenClaw gateway, not direct SSH.
- A successful remote task result must show control_plane=openclaw.
- SSH is only for installing, configuring, or maintaining OpenClaw.

Remote servers:
- 192.168.0.2 is the Hermes scheduler server.
  - Agent roots are under /home/kojima/exdirect.
  - OpenClaw gateway listens on 192.168.0.2:18789.
  - Available backends: codex-cli and claude-cli.
- 192.168.0.14 is the AIxEC API server.
  - Agent roots are under /home/kojima/bittensorman/aidexx.
  - OpenClaw gateway listens on 192.168.0.14:18789.
  - Available backends: codex-cli and claude-cli.
- 192.168.0.11 is the Hyperframes video server.
  - Agent roots are under /home/kojima/exdirect.
  - OpenClaw gateway listens on 192.168.0.11:18789.
  - Available backends: codex-cli and claude-cli.

LLM/backend mapping:
- codex-cli maps to OpenClaw model openai/gpt-5.5 through the Codex app-server harness.
- claude-cli maps to OpenClaw model claude-cli/claude-sonnet-4-6.

Show these flows:
- Smartphone -> kdeck.php -> kdeck FastAPI -> OpenClaw gateway .2 -> Codex/Claude.
- Smartphone -> kdeck.php -> kdeck FastAPI -> OpenClaw gateway .14 -> Codex/Claude.
- Smartphone -> kdeck.php -> kdeck FastAPI -> OpenClaw gateway .11 -> Codex/Claude.
- Optional local path: kdeck FastAPI -> local PTY session on 192.168.0.3.

Show security boundaries:
- Browser never sees API token, OpenClaw gateway token, SSH key, or app credentials.
- PHP proxy and FastAPI are the trusted control path.
- Remote OpenClaw gateways are LAN services with token authentication.
```

## Design Rules

`192.168.0.3` is the only kdeck/SwarmClaw control server. Other machines should not receive kdeck-specific HTTP gateways or cloned application repositories just for orchestration. They run OpenClaw, and SwarmClaw owns task state, shared memory, gateway lifecycle, and routing.

Operational rules:

- Do not add kdeck-specific HTTP gateway code to remote servers.
- Do not clone unrelated application repositories onto a remote server just to make kdeck routing work.
- Do not report success when kdeck merely submitted a task. Success means the selected agent completed and returned a valid result.
- Do not expose OpenClaw tokens, SSH keys, app API tokens, or OAuth credentials to the browser or git.
- Keep app-specific job code inside each app repository. kdeck remains a generic agent deck and orchestration UI.

## Goal Queue Runner

kdeck owns the operational command loop that replaces the old time-based
Hermes enqueue schedules on `192.168.0.2`.

- `kdeck-python-goal-runner.service` currently runs on `192.168.0.3`.
- Python stores state in `storage/controller.sqlite`, refreshes running jobs, and enqueues the next eligible goal.
- Hermes commander is disabled for normal automation until it is redesigned as a true operator/planner instead of a slow cron wrapper.
- RQDB4AI remains the generic execution layer.
- Hermes on `192.168.0.2` is no longer the scheduler. Its cron-like jobs are paused, while OpenClaw remains available for delegated server work.
- A goal is complete only when its business result meets the goal rule, not when RQDB4AI accepted the enqueue request.

The first production goal is `aixec-market-pipeline`:

- per-run target: 500 newly created market items
- daily target: 4000 newly created items, equivalent to 500 x 8 successful runs
- maximum runs per day: effectively unlimited; it keeps running until the daily target is met
- resource lock: `ollama:192.168.0.14:gemma4:e4b`
- cooldown: 900 seconds between attempts

If one run returns fewer than 500 items, kdeck records the partial count.
The runner retries market-pipeline until the daily target is met, but it does not
block every other worker while market is cooling down. During market cooldown,
the runner may run the next eligible goal such as register-market, Horizon, OSS,
Polymarket, FinReport, or buzblogger.

Operational tool surface:

```bash
python3 -m app.commander_tool brief
python3 -m app.commander_tool refresh
python3 -m app.commander_tool status
python3 -m app.commander_tool enqueue <goal_name>
python3 -m app.commander_tool run-once
python3 -m app.commander_tool hold <goal_name>
python3 -m app.commander_tool resume <goal_name>
python3 -m app.commander_tool event warn "message" --data '{}'
```

Manual Python runner turn:

```bash
python3 -m app.commander_tool run-once
```

`brief` returns a small JSON object with `next_goal`, `eligible`, and
`blocked_reason`. `run-once` refreshes running jobs, waits if anything is
running, and otherwise enqueues one eligible goal.

Commander API:

- `GET /api/controller/status`
- `POST /api/controller/tick` runs one Hermes commander turn
- `POST /api/controller/goals/{goal_name}/hold`
- `POST /api/controller/goals/{goal_name}/resume`

The web UI at `kdeck.php` shows Goal Queue, today progress, active/cooldown
state, RQDB4AI live queue counts, worker status, and Hermes decision logs.

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

- `chat-only`: default. Discussion only; Codex is instructed not to run commands, edit files, or operate external services, and it runs with `read-only`.
- `research`: read-only web research and URL verification; Codex is instructed not to run commands, edit files, post, upload, deploy, or mutate external services, and it runs with `read-only`.
- `confirm`: asks in the browser before starting Codex and runs with `workspace-write`.
- `full-access`: runs immediately with `danger-full-access`.

`research`, `confirm`, and `full-access` show an acknowledgement in the chat before the job
starts so the user sees that execution is beginning. Set
`KDECK_DEFAULT_EXECUTION_MODE=chat-only` to keep discussion-only mode selected by default.

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
- `GET /api/controller/status`
- `POST /api/controller/tick`
- `POST /api/controller/goals/{goal_name}/hold`
- `POST /api/controller/goals/{goal_name}/resume`

## Security

- Bind behind firewall/port-forwarding with HTTPS at the edge.
- Use `KDECK_TOKEN` for all API calls.
- Protect `kdeck.php` with `kurage.exbridge.jp` common X login; it can control local shell sessions.
- Allowed working directories are controlled by `KDECK_ALLOWED_ROOTS`.
- Avoid sudo from mobile sessions.
