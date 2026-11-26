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


# ---------------------------------------------------------------- Solana (read-only)

# Public RPC works but is rate-limited. For heavy use, point SOLANA_RPC_URL at a free
# Helius / QuickNode / Alchemy endpoint.
SOLANA_RPC = os.getenv("SOLANA_RPC_URL", "https://api.mainnet-beta.solana.com")
SPL_TOKEN_PROGRAM = "TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA"
TOKEN_2022_PROGRAM = "TokenzQdBNbLqP5VEhdkAS6EPFLC1PHnBqCXEpPxuEb"
WRAPPED_SOL_MINT = "So11111111111111111111111111111111111111112"


async def solana_rpc(client: httpx.AsyncClient, method: str, params: list[Any]) -> Any:
    response = await client.post(SOLANA_RPC, json={"jsonrpc": "2.0", "id": 1, "method": method, "params": params})
    response.raise_for_status()
    body = response.json()
    if body.get("error"):
        raise httpx.HTTPError(f"Solana RPC {method}: {body['error'].get('message')}")
    return body.get("result")


async def solana_balance_sol(client: httpx.AsyncClient, address: str) -> float:
    result = await solana_rpc(client, "getBalance", [address])
    return (result or {}).get("value", 0) / 1e9


async def solana_token_holdings(client: httpx.AsyncClient, address: str) -> dict[str, float]:
    """mint -> amount held, across classic SPL and Token-2022 accounts (zero balances dropped)."""
    holdings: dict[str, float] = {}
    for program in (SPL_TOKEN_PROGRAM, TOKEN_2022_PROGRAM):
        result = await solana_rpc(
            client, "getTokenAccountsByOwner", [address, {"programId": program}, {"encoding": "jsonParsed"}]
        )
        for acc in (result or {}).get("value", []):
            info = acc.get("account", {}).get("data", {}).get("parsed", {}).get("info", {})
            amount = (info.get("tokenAmount") or {}).get("uiAmount") or 0
            if info.get("mint") and amount > 0:
                holdings[info["mint"]] = holdings.get(info["mint"], 0) + amount
    return holdings


async def dex_best_pairs(client: httpx.AsyncClient, chain_id: str, mints: list[str]) -> dict[str, dict[str, Any]]:
    """Most liquid DexScreener pair per token address (30 addresses per request)."""
    best: dict[str, dict[str, Any]] = {}
    for i in range(0, len(mints), 30):
        chunk = mints[i : i + 30]
        data = await _get_json(client, f"{DEXSCREENER}/tokens/v1/{chain_id}/{','.join(chunk)}")
        for pair in data if isinstance(data, list) else []:
            mint = (pair.get("baseToken") or {}).get("address")
            if mint not in chunk:
                continue
            liq = (pair.get("liquidity") or {}).get("usd") or 0
            current = best.get(mint)
            if current is None or liq > ((current.get("liquidity") or {}).get("usd") or 0):
                best[mint] = pair
    return best


# ---------------------------------------------------------------- canonical contract resolution

# CoinGecko platform ids -> DexScreener chain ids
GECKO_TO_DEX_CHAIN = {"binance-smart-chain": "bsc", "polygon-pos": "polygon", "arbitrum-one": "arbitrum"}


async def gecko_search(client: httpx.AsyncClient, query: str) -> list[dict[str, Any]]:
    data = await _get_json(client, f"{COINGECKO}/search", {"query": query})
    return data.get("coins") or []


async def gecko_platforms(client: httpx.AsyncClient, coin_id: str) -> dict[str, str]:
    params = {"localization": "false", "tickers": "false", "market_data": "false",
              "community_data": "false", "developer_data": "false"}
    data = await _get_json(client, f"{COINGECKO}/coins/{coin_id}", params)
    return {GECKO_TO_DEX_CHAIN.get(k, k): v for k, v in (data.get("platforms") or {}).items() if k and v}
