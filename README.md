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
Chat threads are saved under `KDECK_DATA_DIR` so the web UI can reopen recent Codex conversations.

See [Kurage Agent Deck の技術解説](docs/kurage-agent-deck-technical-overview.md) for a Japanese technical overview.

## Setup

Create `.env` from `.env.sample` and set a strong token.

```bash
cp .env.sample .env
python3 -m venv .venv
. .venv/bin/activate
pip install -r requirements.txt
scripts/run_kdeck.sh
```

`KDECK_CODEX_SANDBOX` controls the Codex CLI sandbox mode. Use `danger-full-access`
only on a trusted, login-protected deployment when Codex needs network access for
operations such as `git push`.

## API

- `GET /healthz`
- `GET /api/sessions`
- `POST /api/sessions`
- `GET /api/sessions/{id}/capture`
- `POST /api/sessions/{id}/send`
- `POST /api/sessions/{id}/interrupt`
- `POST /api/sessions/{id}/terminate`

## Security

- Bind behind firewall/port-forwarding with HTTPS at the edge.
- Use `KDECK_TOKEN` for all API calls.
- Protect `kdeck.php` with `kurage.exbridge.jp` common X login; it can control local shell sessions.
- Allowed working directories are controlled by `KDECK_ALLOWED_ROOTS`.
- Avoid sudo from mobile sessions.
