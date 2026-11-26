"""Run the research agent straight from the terminal - no Agent Stack platform needed.

Same tools and same analyst instructions as agent.py, with Claude via the official Anthropic SDK.

    export ANTHROPIC_API_KEY=...        # https://console.anthropic.com
    uv run research "What meme coins are trending right now?"
    uv run research --no-second-opinion "Research WIF"     # skip the critic pass
"""

from __future__ import annotations

import asyncio
import json
import sys

import anthropic
from anthropic import beta_async_tool

from meme_crypto_agent.critic import CRITIC_INSTRUCTIONS, build_critic_message
from meme_crypto_agent.tools import MarketOverviewTool, TokenLookupTool, TrendingTool
from meme_crypto_agent.wallet import SECRET_WARNING, WalletWatchTool, looks_like_secret

MODEL = "claude-opus-5-5"


def _instructions() -> str:
    # Reuse the analyst prompt from the Agent Stack agent; tool names match.
    from meme_crypto_agent.agent import INSTRUCTIONS

    return INSTRUCTIONS.replace("Use DuckDuckGo", "Use web_search")


async def _call(tool, **kwargs) -> str:
    out = await tool.run(kwargs)
    return out.get_text_content()


@beta_async_tool(name="TokenLookup")
async def token_lookup(query: str, chain: str | None = None, limit: int = 5) -> str:
    """Look up a meme coin or any DEX-traded token on DexScreener: price, liquidity, volume, buys/sells,
    age, socials, an automatic red-flag risk score, and manual verification links.

    Args:
        query: Token name, ticker (e.g. 'PEPE', 'WIF') or contract address.
        chain: Optional chain filter, e.g. 'solana', 'ethereum', 'base', 'bsc'.
        limit: How many pairs to return, sorted by liquidity (1-10).
    """
    return await _call(TokenLookupTool(), query=query, chain=chain, limit=max(1, min(limit, 10)))


@beta_async_tool(name="TrendingRadar")
async def trending_radar(limit: int = 10) -> str:
    """What's hot right now: CoinGecko most-searched coins (organic attention) plus DexScreener's most
    boosted tokens (PAID promotion).

    Args:
        limit: Max items per source (1-25).
    """
    return await _call(TrendingTool(), limit=max(1, min(limit, 25)))


@beta_async_tool(name="MarketOverview")
async def market_overview(coin_ids: list[str] | None = None, category: str | None = None, limit: int = 10) -> str:
    """CoinGecko market data: price, market cap, rank, volume, 1h/24h/7d change, distance from ATH.

    Args:
        coin_ids: CoinGecko ids, e.g. ['bitcoin','ethereum','solana','dogecoin'].
        category: CoinGecko category id, e.g. 'meme-token' for the top meme coins.
        limit: Number of coins (1-50).
    """
    return await _call(MarketOverviewTool(), coin_ids=coin_ids, category=category, limit=max(1, min(limit, 50)))


@beta_async_tool(name="WalletWatch")
async def wallet_watch(address: str, min_value_usd: float = 1.0, limit: int = 25) -> str:
    """Read-only Solana portfolio check from a PUBLIC wallet address: SOL balance, every token with live
    price and USD value, portfolio share, a red-flag risk score per holding, and alerts.

    Args:
        address: PUBLIC Solana wallet address (base58). Never a seed phrase or private key.
        min_value_usd: Hide positions worth less than this (dust).
        limit: Max positions to return, largest first (1-100).
    """
    return await _call(WalletWatchTool(), address=address, min_value_usd=max(0, min_value_usd), limit=max(1, min(limit, 100)))


async def _run(client: anthropic.AsyncAnthropic, system: str, content: str) -> str:
    runner = client.beta.messages.tool_runner(
        model=MODEL,
        max_tokens=16000,
        system=system,
        output_config={"effort": "high"},
        betas=["server-side-fallback-2026-07-01"],
        fallbacks="default",  # if a safety classifier declines, the API retries on a suitable model
        tools=[
            token_lookup,
            trending_radar,
            market_overview,
            wallet_watch,
            {"type": "web_search_20260209", "name": "web_search", "max_uses": 5},
        ],
        messages=[{"role": "user", "content": content}],
    )
    final = None
    async for message in runner:
        final = message
        for block in message.content:
            if block.type == "tool_use":
                print(f"  -> {block.name}({json.dumps(block.input)[:120]})", file=sys.stderr)
            elif block.type == "server_tool_use":
                print(f"  -> {block.name}: {json.dumps(block.input)[:120]}", file=sys.stderr)
    if final is None:
        return "(no response)"
    if final.stop_reason == "refusal":
        return "The model declined this request."
    return "".join(b.text for b in final.content if b.type == "text")


async def research(question: str, second_opinion: bool = True) -> str:
    client = anthropic.AsyncAnthropic()
    print("[1/2] Research pass" if second_opinion else "[1/1] Research pass", file=sys.stderr)
    report = await _run(client, _instructions(), question)
    if not second_opinion or report in ("(no response)", "The model declined this request."):
        return report
    print("[2/2] Second-opinion pass", file=sys.stderr)
    review = await _run(client, CRITIC_INSTRUCTIONS, build_critic_message(question, report))
    return f"{report}\n\n---\n\n## Second Opinion\n\n{review}"


def main() -> None:
    args = sys.argv[1:]
    second_opinion = "--no-second-opinion" not in args
    question = " ".join(a for a in args if a != "--no-second-opinion") or "What meme coins are trending right now?"
    if looks_like_secret(question):
        sys.exit(SECRET_WARNING)
    print(asyncio.run(research(question, second_opinion=second_opinion)))


if __name__ == "__main__":
    main()
