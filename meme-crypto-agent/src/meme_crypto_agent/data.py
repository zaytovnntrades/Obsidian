"""Thin async clients for FREE, no-signup crypto data sources.

- DexScreener: on-chain DEX pairs on every major chain. This is where meme coins live.
  Docs: https://docs.dexscreener.com/api/reference  (no key, ~300 req/min)
- CoinGecko: majors, market caps, trending searches.
  Docs: https://docs.coingecko.com  (works keyless; set COINGECKO_API_KEY for a free "demo" key = higher limits)

Every function takes an ``httpx.AsyncClient`` so tests can inject a fake transport.
"""

from __future__ import annotations

import os
from typing import Any

import httpx

DEXSCREENER = "https://api.dexscreener.com"
COINGECKO = "https://api.coingecko.com/api/v3"


def make_client() -> httpx.AsyncClient:
    headers = {"Accept": "application/json", "User-Agent": "meme-crypto-research-agent/0.1"}
    if key := os.getenv("COINGECKO_API_KEY"):
        headers["x-cg-demo-api-key"] = key
    return httpx.AsyncClient(timeout=20, headers=headers, follow_redirects=True)


async def _get_json(client: httpx.AsyncClient, url: str, params: dict[str, Any] | None = None) -> Any:
    response = await client.get(url, params=params)
    response.raise_for_status()
    return response.json()


# ---------------------------------------------------------------- DexScreener


async def dex_search(client: httpx.AsyncClient, query: str) -> list[dict[str, Any]]:
    """Search pairs by token name, symbol, or contract/pair address."""
    data = await _get_json(client, f"{DEXSCREENER}/latest/dex/search", {"q": query})
    return data.get("pairs") or []


async def dex_top_boosted(client: httpx.AsyncClient) -> list[dict[str, Any]]:
    """Tokens with the most *paid* DexScreener boosts right now (promotion, not organic demand)."""
    data = await _get_json(client, f"{DEXSCREENER}/token-boosts/top/v1")
    return data if isinstance(data, list) else []


async def dex_token_pairs(client: httpx.AsyncClient, chain_id: str, token_address: str) -> list[dict[str, Any]]:
    data = await _get_json(client, f"{DEXSCREENER}/token-pairs/v1/{chain_id}/{token_address}")
    return data if isinstance(data, list) else []


# ---------------------------------------------------------------- CoinGecko


async def gecko_trending(client: httpx.AsyncClient) -> list[dict[str, Any]]:
    """Coins people are searching for most on CoinGecko in the last 24h."""
    data = await _get_json(client, f"{COINGECKO}/search/trending")
    return [c.get("item", {}) for c in data.get("coins", [])]


async def gecko_markets(
    client: httpx.AsyncClient, ids: list[str] | None = None, category: str | None = None, limit: int = 10
) -> list[dict[str, Any]]:
    params: dict[str, Any] = {
        "vs_currency": "usd",
        "order": "market_cap_desc",
        "per_page": limit,
        "page": 1,
        "price_change_percentage": "1h,24h,7d",
    }
    if ids:
        params["ids"] = ",".join(ids)
    if category:
        params["category"] = category  # e.g. "meme-token"
    data = await _get_json(client, f"{COINGECKO}/coins/markets", params)
    return data if isinstance(data, list) else []
