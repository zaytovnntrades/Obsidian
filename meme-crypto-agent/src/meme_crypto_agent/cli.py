"""Call the data tools directly and print JSON - no LLM, no API key.

This is what the Claude Code subagents (.claude/agents/) use: Claude Code itself is the brain,
these commands are its hands.

    uv run -q tools TokenLookup '{"query": "WIF", "chain": "solana"}'
    uv run -q tools TrendingRadar '{"limit": 10}'
    uv run -q tools MarketOverview '{"category": "meme-token", "limit": 10}'
    uv run -q tools WalletWatch '{"address": "<public address>"}'
"""

from __future__ import annotations

import asyncio
import json
import sys

from meme_crypto_agent.tools import MarketOverviewTool, TokenLookupTool, TrendingTool
from meme_crypto_agent.wallet import SECRET_WARNING, WalletWatchTool, looks_like_secret

TOOLS = {
    "TokenLookup": TokenLookupTool,
    "TrendingRadar": TrendingTool,
    "MarketOverview": MarketOverviewTool,
    "WalletWatch": WalletWatchTool,
}


async def run(name: str, args: dict) -> str:
    return (await TOOLS[name]().run(args)).get_text_content()


def main() -> None:
    if len(sys.argv) < 2 or sys.argv[1] not in TOOLS:
        sys.exit(f"usage: tools <{'|'.join(TOOLS)}> '<json args>'")
    raw = sys.argv[2] if len(sys.argv) > 2 else "{}"
    if looks_like_secret(raw):
        sys.exit(SECRET_WARNING)
    try:
        print(asyncio.run(run(sys.argv[1], json.loads(raw))))
    except Exception as e:  # noqa: BLE001 - surface any tool error as JSON for the calling agent
        print(json.dumps({"error": f"{type(e).__name__}: {e}"}))
        sys.exit(1)


if __name__ == "__main__":
    main()
