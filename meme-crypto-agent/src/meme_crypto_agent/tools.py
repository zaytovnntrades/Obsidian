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
from meme_crypto_agent.risk import aggregate_pools, summarize_pair

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
        chain = input.chain.lower() if input.chain else None
        async with self._client_factory() as client:
            pairs = await data.dex_search(client, input.query)
            canonical = await self._canonical_pair(client, input.query, chain)
        if chain:
            pairs = [p for p in pairs if p.get("chainId") == chain]
        pairs.sort(key=lambda p: (p.get("liquidity") or {}).get("usd") or 0, reverse=True)

        canonical_address = None
        if canonical:
            pair, coin = canonical
            canonical_address = (pair.get("baseToken") or {}).get("address")
            pairs = [pair] + [p for p in pairs if (p.get("baseToken") or {}).get("address") != canonical_address]

        # one entry per token (search returns several pairs of the same token), in ranked order
        tokens: list[dict[str, Any]] = []
        seen: set[str] = set()
        for pair in pairs:
            addr = (pair.get("baseToken") or {}).get("address")
            if addr and addr not in seen:
                seen.add(addr)
                tokens.append(pair)
            if len(tokens) >= input.limit:
                break
        pools: dict[tuple[str, str], list[dict[str, Any]]] = {}
        async with self._client_factory() as client:
            for chain_id in {p.get("chainId") for p in tokens if p.get("chainId")}:
                addrs = [p["baseToken"]["address"] for p in tokens if p.get("chainId") == chain_id]
                for addr, found in (await data.dex_all_pools(client, chain_id, addrs)).items():
                    pools[(chain_id, addr)] = found

        results = []
        for pair in tokens:
            addr = pair["baseToken"]["address"]
            totals = aggregate_pools(pools.get((pair.get("chainId"), addr), []), addr)
            summary = summarize_pair(pair, totals)
            summary["verify_links"] = verify_links(summary["chain"], summary["token_address"])
            if canonical_address and summary["token_address"] == canonical_address:
                summary["canonical"] = {"source": "CoinGecko", "id": coin["id"], "market_cap_rank": coin.get("market_cap_rank")}
            results.append(summary)

        note = None
        if len({r["token_address"] for r in results}) > 1:
            note = "Multiple tokens share this ticker. Copycats are common - confirm the contract address."
            if canonical_address:
                note += " The first result is the CoinGecko-listed contract; the rest are OTHER tokens."
        return JSONToolOutput({"query": input.query, "count": len(results), "pairs": results, "note": note})

    async def _canonical_pair(self, client, query: str, chain: str | None):
        """For a ticker like 'WIF', find the CoinGecko-listed contract and its most liquid DEX pair.

        DexScreener search ranks by text match, so for popular tickers it can return only tiny copycats
        and miss the real coin. CoinGecko's listing is the tie-breaker.
        """
        symbol = query.strip().lstrip("$").lower()
        if len(symbol) > 15 or " " in symbol or len(query) >= 32:  # looks like a name or an address
            return None
        try:
            coins = [c for c in await data.gecko_search(client, symbol)
                     if (c.get("symbol") or "").lstrip("$").lower() == symbol and c.get("market_cap_rank")]
            if not coins:
                return None
            coin = min(coins, key=lambda c: c["market_cap_rank"])
            platforms = await data.gecko_platforms(client, coin["id"])
            for dex_chain, address in platforms.items():
                if chain and dex_chain != chain:
                    continue
                best = (await data.dex_best_pairs(client, dex_chain, [address])).get(address)
                if best:
                    return best, coin
        except httpx.HTTPError:
            return None  # fall back to plain search results
        return None


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
