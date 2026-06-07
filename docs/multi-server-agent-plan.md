# kdeck Multi-Server Agent Plan

## Summary

`192.168.0.3` is the kdeck integration server and the SwarmClaw control plane.
Remote servers run OpenClaw/Codex for actual work.
kdeck does not talk directly to per-server HTTP agent gateways.

## Roles

- `192.168.0.3`: kdeck UI/API, SwarmClaw, task history, shared memory, operator entry point.
- `192.168.0.2`: Hermes scheduler work through an OpenClaw runtime.
- `192.168.0.14`: AIxEC API server work through an OpenClaw runtime.
- `192.168.0.11`: Hyperframes video work through an OpenClaw runtime.

## Current State

- SwarmClaw runs on `192.168.0.3` at `127.0.0.1:3456`.
- `192.168.0.14` has an OpenClaw gateway profile registered as `openclaw-192-168-0-14`.
- The `.14` OpenClaw gateway is LAN-bound on port `18789` with token authentication.
- kdeck should keep `target_agent` in chat/task history, but routing should go through SwarmClaw gateway profiles.

## Rules

- Do not add kdeck-specific HTTP gateway code to remote servers.
- Do not clone application repositories onto a remote server just to make kdeck routing work.
- Remote servers should contain only their own normal application files plus OpenClaw/SwarmClaw-related runtime files.
- Browser HTML must never contain SwarmClaw access keys, OpenClaw gateway tokens, SSH keys, or app credentials.
- A task is successful only when the selected agent reports completed work, not when kdeck merely submits it.

## Environment

```text
SWARMCLAW_BASE_URL=http://127.0.0.1:3456
SWARMCLAW_HOME=/home/kojima/.swarmclaw
```

The SwarmClaw access key is stored outside git under `SWARMCLAW_HOME`.
