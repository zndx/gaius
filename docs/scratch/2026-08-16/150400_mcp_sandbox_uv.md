# Gaius MCP died under workspace sandbox

`uv run` could not write `~/.cache/uv` (EACCES). Handshake closed
in 17ms; sitrep then searched tools and found nothing.

Session config now starts `.devenv/state/venv/bin/python -m
gaius.mcp_server` with `PYTHONDONTWRITEBYTECODE=1`, disables
cybersec, and sets `max_retries = 2` for local Complete.
