# Kurage Agent Deck (kdeck)

Kurage Agent Deck is a small mobile web console for controlling local coding-agent CLI sessions on this Linux server.

Initial target:

- Project name: Kurage Agent Deck
- Folder: `kdeck`
- API: FastAPI on port `18301`
- Web: `https://kurage.exbridge.jp/kdeck.php`
- Runtime: tmux + Codex CLI

## Architecture

```text
Smartphone browser
  -> kurage.exbridge.jp/kdeck.php
  -> PHP server-side proxy
  -> http://<linux-server>:18301
  -> FastAPI
  -> tmux sessions
  -> codex CLI
```

The PHP page keeps the API token on the web server side. The browser talks to PHP, not directly to FastAPI.

## Setup

Create `.env` from `.env.sample` and set a strong token.

```bash
cp .env.sample .env
python3 -m venv .venv
. .venv/bin/activate
pip install -r requirements.txt
scripts/run_kdeck.sh
```

## API

- `GET /healthz`
- `GET /api/sessions`
- `POST /api/sessions`
- `GET /api/sessions/{id}/capture`
- `POST /api/sessions/{id}/send`
- `POST /api/sessions/{id}/interrupt`

## Security

- Bind behind firewall/port-forwarding with HTTPS at the edge.
- Use `KDECK_TOKEN` for all API calls.
- Allowed working directories are controlled by `KDECK_ALLOWED_ROOTS`.
- Avoid sudo from mobile sessions.
