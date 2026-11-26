# Obsidian research workspace

## Layout
- `meme-crypto-agent/` - Python data tools + Agent Stack agent. `uv run -q tools <Tool> '<json>'` prints JSON (no API key needed).
- `.claude/agents/` - specialist subagents: crypto-researcher, crypto-critic, web-clipper, vault-writer, canvas-mapper.
- `scripts/canvas_tool.py` - mind-map layout + validation for `.canvas` files (`layout <spec.json> -o <out.canvas>`, `validate <file>`).
- `.claude/skills/` - the skill stack. `research-desk` is the orchestrator; the rest are installed with `scripts/add_skills.py` (see `.claude/skills/README.md`).
- `vault/` - Obsidian notes the desk writes. Dashboard: `vault/Watchlist.base`.

## Adding skills
`python3 scripts/add_skills.py <git-url> [--only a,b] [--agent <agent-name>]` - copies every SKILL.md folder into
`.claude/skills/`, records it in `skills.lock.json`, and preloads it into the named agents. Review new skills before use.

## Rules
- Never ask for, store, or repeat seed phrases or private keys. Wallets are read-only via public address.
- Notes never contain full wallet addresses.
- Research only - not financial advice.
- Tests: `cd meme-crypto-agent && uv run -q pytest -q`
