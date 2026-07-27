# CogniOS Claude Code Integration

This directory contains the Claude Code skill bundle for CogniOS.

## User Flow

1. Open CogniOS Settings > Integrations.
2. Add a Claude Agent.
3. Copy the full setup commands shown after the generated token.
4. Toggle the tools Claude is allowed to use.
5. Configure the terminal Claude Code session:

```bash
export COGNIOS_URL=http://your-cognios-host:7000
export COGNIOS_API_TOKEN=ody_generated_token
mkdir -p ~/.claude
curl -fsSL -H "Authorization: Bearer $COGNIOS_API_TOKEN" "$COGNIOS_URL/api/claude/plugin.zip" -o /tmp/cognios-claude-skill.zip
python3 -m zipfile -e /tmp/cognios-claude-skill.zip ~/.claude/
```

Claude Code auto-loads anything under `~/.claude/skills/`, so the `cognios` skill is
available in any session that has `COGNIOS_URL` and `COGNIOS_API_TOKEN` in its
environment.

## What's in the bundle

- `skills/cognios/SKILL.md` — the skill definition Claude Code reads.
- `skills/cognios/scripts/cognios_api.py` — small helper that calls the scoped
  `/api/codex/*` endpoints (these are the canonical scope-gated agent API; the
  `codex` path is historic and shared by all agent integrations).

## Scope enforcement

The token is scope-gated. Every tool surface is checked server-side in CogniOS,
so even if Claude tries to call a forbidden endpoint, it gets `403` until the
user enables the matching toggle in Settings > Integrations > Claude Agent.
