# kdeck Multi-Server Agent Plan

## Summary

`192.168.0.3` is the kdeck integration server. It owns the browser UI, task history, and shared memory. Other servers run role-specific agent gateways and receive tasks from kdeck or a future SwarmClaw control plane.

## Agents

- `local`: kdeck local Codex on `192.168.0.3`.
- `hermes-192-168-0-2`: Hermes scheduler agent on `192.168.0.2`.
- `aixec-api-192-168-0-14`: AIxEC API server agent on `192.168.0.14`.
- `hyperframes-192-168-0-11`: Hyperframes video generation agent on `192.168.0.11`.

## Current PoC Interface

- kdeck exposes agent metadata from `/api/config` and `/api/agents`.
- The web UI sends `target_agent` with each `/api/chat` request.
- Local tasks continue to run through Codex CLI on this server.
- Remote tasks require the matching `KDECK_AGENT_*_API_BASE` environment variable. If the API base is not configured, kdeck returns a clear failure instead of pretending the task succeeded.
- Task records are saved under `KDECK_DATA_DIR/agent_tasks`.
- Short shared-memory summaries are saved under `KDECK_DATA_DIR/shared_memory`.

## Environment

```text
KDECK_AGENT_TOKEN=
KDECK_AGENT_HERMES_API_BASE=http://192.168.0.2:<port>
KDECK_AGENT_AIXEC_API_BASE=http://192.168.0.14:<port>
KDECK_AGENT_HYPERFRAMES_API_BASE=http://192.168.0.11:<port>
```

Use per-agent tokens later with:

```text
KDECK_AGENT_TOKEN_HERMES_192_168_0_2=
KDECK_AGENT_TOKEN_AIXEC_API_192_168_0_14=
KDECK_AGENT_TOKEN_HYPERFRAMES_192_168_0_11=
```

## Rules

- kdeck is the only browser-facing entry point.
- Agent gateway APIs must be LAN-only and protected by bearer tokens.
- Browser HTML must never contain agent tokens.
- Remote tasks must not be marked successful unless the remote agent returns a completed result.
- SwarmClaw can replace the direct remote API dispatch later, but the kdeck UI should keep the same `target_agent` concept.
