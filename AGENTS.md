# kdeck Agent Rules

- kdeck is the control plane for Goal Queue and multi-server agent routing.
- rqdb4ai must remain generic. Do not add app-specific job implementations to rqdb4ai.
- App-specific job code belongs in the owning repository.
- Use `/home/kojima/work/...` paths on this server.
- Pull before editing repositories that may be changed from other servers.
- Do not commit or print secrets.
- For growth operations, prefer `python3 -m app.commander_tool growth-cycle`.
- Treat enqueue success and business success as different states.
