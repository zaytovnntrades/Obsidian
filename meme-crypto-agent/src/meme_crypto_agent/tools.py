"""BeeAI tools the LLM can call. Each wraps one data source and returns compact JSON."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any, Self

import httpx
from beeai_framework.context import RunContext
from beeai_framework.emitter import Emitter
from beeai_framework.tools import JSONToolOutput, Tool, ToolRunOptions
from pydantic import BaseModel, Field

from meme_crypto_agent import data
from meme_crypto_agent.risk import summarize_pair

ClientFactory = Callable[[], httpx.AsyncClient]


def verify_links(chain: str | None, address: str | None) -> dict[str, str]:
    """Manual security checks a human should always run before buying."""
    if not address:
        return {}
    links = {"bubblemaps_holders": f"https://app.bubblemaps.io/{chain}/token/{address}"}
    if chain == "solana":
        links["rugcheck"] = f"https://rugcheck.xyz/tokens/{address}"
    else:
        links["honeypot_is"] = f"https://honeypot.is/?address={address}"
        links["tokensniffer"] = f"https://tokensniffer.com/token/{chain}/{address}"
    return links


class _BaseTool(Tool):  # type: ignore[type-arg]
    def __init__(self, client_factory: ClientFactory = data.make_client, options: dict[str, Any] | None = None):
        super().__init__(options)
        self._client_factory = client_factory

    def _create_emitter(self) -> Emitter:
        return Emitter.root().child(namespace=["tool", "crypto", self.name.lower()], creator=self)

    async def clone(self) -> Self:
        tool = self.__class__(client_factory=self._client_factory, options=self.options)
        tool.middlewares.extend(self.middlewares)
        return tool


# ------------------------------------------------------------------ token lookup


class TokenLookupInput(BaseModel):
    query: str = Field(description="Token name, ticker (e.g. 'PEPE', 'WIF') or contract address.")
    chain: str | None = Field(
        default=None, description="Optional chain filter, e.g. 'solana', 'ethereum', 'base', 'bsc'."
    )
    limit: int = Field(default=5, ge=1, le=10, description="How many pairs to return (sorted by liquidity).")


class TokenLookupTool(_BaseTool):
    name = "TokenLookup"
    description = (
        "Look up a meme coin or any DEX-traded token on DexScreener. Returns price, liquidity, volume, "
        "buy/sell counts, age, socials, an automatic red-flag risk score, and manual verification links. "
        "Use this first for any specific token the user asks about."
    )
    input_schema = TokenLookupInput

    async def _run(
        self, input: TokenLookupInput, options: ToolRunOptions | None, context: RunContext
    ) -> JSONToolOutput[dict[str, Any]]:
        async with self._client_factory() as client:
            pairs = await data.dex_search(client, input.query)
        if input.chain:
            pairs = [p for p in pairs if p.get("chainId") == input.chain.lower()]
        pairs.sort(key=lambda p: (p.get("liquidity") or {}).get("usd") or 0, reverse=True)

        results = []
        for pair in pairs[: input.limit]:
            summary = summarize_pair(pair)
            summary["verify_links"] = verify_links(summary["chain"], summary["token_address"])
            results.append(summary)

        note = (
            "Multiple tokens share tickers. Copycats are common - confirm the contract address."
            if len({r["token_address"] for r in results}) > 1
            else None
        )
        return JSONToolOutput({"query": input.query, "count": len(results), "pairs": results, "note": note})


# ------------------------------------------------------------------ trending


class TrendingInput(BaseModel):
    limit: int = Field(default=10, ge=1, le=25, description="Max items per source.")


class TrendingTool(_BaseTool):
    name = "TrendingRadar"
    description = (
        "What's hot right now: CoinGecko's most-searched coins (organic attention) plus DexScreener's most "
        "boosted tokens (PAID promotion). Use for 'what's trending', 'find new memes', or idea generation."
    )
    input_schema = TrendingInput

    async def _run(
        self, input: TrendingInput, options: ToolRunOptions | None, context: RunContext
    ) -> JSONToolOutput[dict[str, Any]]:
        out: dict[str, Any] = {"errors": []}
        async with self._client_factory() as client:
            try:
                trending = await data.gecko_trending(client)
                out["coingecko_trending_searches"] = [
                    {
                        "id": c.get("id"),
                        "name": c.get("name"),
                        "symbol": c.get("symbol"),
                        "market_cap_rank": c.get("market_cap_rank"),
                        "price_usd": (c.get("data") or {}).get("price"),
                        "change_24h_pct": ((c.get("data") or {}).get("price_change_percentage_24h") or {}).get("usd"),
                    }
                    for c in trending[: input.limit]
                ]
            except httpx.HTTPError as e:
                out["errors"].append(f"coingecko: {e}")
            try:
                boosted = await data.dex_top_boosted(client)
                out["dexscreener_paid_boosts"] = [
                    {
                        "chain": b.get("chainId"),
                        "token_address": b.get("tokenAddress"),
                        "boost_amount": b.get("totalAmount"),
                        "description": (b.get("description") or "")[:200],
                        "url": b.get("url"),
                    }
                    for b in boosted[: input.limit]
                ]
            except httpx.HTTPError as e:
                out["errors"].append(f"dexscreener: {e}")
        out["reminder"] = "Boosts are paid ads. Trending searches = attention, not quality. Run TokenLookup next."
        return JSONToolOutput(out)


# ------------------------------------------------------------------ market overview


class MarketInput(BaseModel):
    coin_ids: list[str] | None = Field(
        default=None,
        description="CoinGecko ids, e.g. ['bitcoin','ethereum','solana','dogecoin']. Leave empty with "
        "category='meme-token' to get the top meme coins by market cap.",
    )
    category: str | None = Field(default=None, description="CoinGecko category id, e.g. 'meme-token'.")
    limit: int = Field(default=10, ge=1, le=50)


class MarketOverviewTool(_BaseTool):
    name = "MarketOverview"
    description = (
        "Market data for established coins from CoinGecko: price, market cap, rank, volume, 1h/24h/7d change, "
        "distance from all-time high. Use for majors (BTC, ETH, SOL), top meme coins, and market context."
    )
    input_schema = MarketInput

    async def _run(
        self, input: MarketInput, options: ToolRunOptions | None, context: RunContext
    ) -> JSONToolOutput[dict[str, Any]]:
        ids = input.coin_ids or (None if input.category else ["bitcoin", "ethereum", "solana"])
        async with self._client_factory() as client:
            rows = await data.gecko_markets(client, ids=ids, category=input.category, limit=input.limit)
        keep = (
            "id symbol name current_price market_cap market_cap_rank total_volume "
            "price_change_percentage_1h_in_currency price_change_percentage_24h_in_currency "
            "price_change_percentage_7d_in_currency ath ath_change_percentage"
        ).split()
        return JSONToolOutput({"coins": [{k: r.get(k) for k in keep} for r in rows]})
