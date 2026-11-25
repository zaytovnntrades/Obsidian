"""Offline tests: fake HTTP responses, no network or LLM needed.  Run: uv run pytest"""

import json
import time

import httpx

from meme_crypto_agent.risk import score_pair
from meme_crypto_agent.tools import MarketOverviewTool, TokenLookupTool, TrendingTool

NOW = time.time() * 1000
HOUR = 3_600_000


def pair(**over):
    base = {
        "chainId": "solana",
        "dexId": "raydium",
        "url": "https://dexscreener.com/solana/abc",
        "baseToken": {"address": "TokenAAA", "name": "Dog Wif Hat", "symbol": "WIF"},
        "quoteToken": {"symbol": "SOL"},
        "priceUsd": "1.23",
        "txns": {"h24": {"buys": 900, "sells": 800}},
        "volume": {"h24": 2_000_000},
        "priceChange": {"h24": 5},
        "liquidity": {"usd": 5_000_000},
        "fdv": 1_200_000_000,
        "pairCreatedAt": NOW - 400 * 24 * HOUR,
        "info": {"websites": [{"url": "https://example.com"}], "socials": [{"url": "https://x.com/x"}]},
    }
    base.update(over)
    return base


# ------------------------------------------------------------------ risk scorer


def test_established_token_is_lower_risk():
    r = score_pair(pair(), now_ms=NOW)
    assert r.level == "LOWER", r.flags


def test_fresh_thin_honeypot_is_high_risk():
    r = score_pair(
        pair(
            liquidity={"usd": 4_000},
            pairCreatedAt=NOW - 2 * HOUR,
            txns={"h24": {"buys": 300, "sells": 0}},
            fdv=2_000_000,
            priceChange={"h24": 900},
            info={},
        ),
        now_ms=NOW,
    )
    assert r.level == "HIGH"
    text = " ".join(r.flags)
    for needle in ("thin liquidity", "Brand-new", "honeypot", "No website", "liquidity -"):
        assert needle in text, needle


def test_heavy_dumping_is_not_lower_risk():
    # Real case seen live: 911 buys vs 27,288 sells on a $36k-liquidity pool.
    r = score_pair(pair(liquidity={"usd": 36_500}, txns={"h24": {"buys": 911, "sells": 27_288}}), now_ms=NOW)
    assert r.level != "LOWER"
    assert any("Heavy dumping" in f for f in r.flags)


def test_missing_fields_do_not_crash():
    r = score_pair({}, now_ms=NOW)
    assert 0 <= r.score <= 100


# ------------------------------------------------------------------ tools (mocked HTTP)


def fake_client_factory(routes):
    def handler(request: httpx.Request) -> httpx.Response:
        for prefix, payload in routes.items():
            if request.url.path.startswith(prefix):
                return httpx.Response(200, json=payload)
        return httpx.Response(404)

    return lambda: httpx.AsyncClient(transport=httpx.MockTransport(handler))


async def test_token_lookup_sorts_filters_and_warns_on_copycats():
    copycat = pair(baseToken={"address": "FakeBBB", "name": "WIF", "symbol": "WIF"}, liquidity={"usd": 900})
    on_eth = pair(chainId="ethereum")
    tool = TokenLookupTool(fake_client_factory({"/latest/dex/search": {"pairs": [copycat, pair(), on_eth]}}))
    out = json.loads((await tool.run({"query": "WIF", "chain": "solana"})).get_text_content())

    assert out["count"] == 2
    assert out["pairs"][0]["token_address"] == "TokenAAA"  # most liquid first
    assert "rugcheck" in out["pairs"][0]["verify_links"]
    assert out["note"] and "Copycats" in out["note"]


async def test_trending_merges_both_sources():
    tool = TrendingTool(
        fake_client_factory(
            {
                "/api/v3/search/trending": {"coins": [{"item": {"id": "pepe", "name": "Pepe", "symbol": "PEPE"}}]},
                "/token-boosts/top/v1": [{"chainId": "base", "tokenAddress": "0xabc", "totalAmount": 500}],
            }
        )
    )
    out = json.loads((await tool.run({})).get_text_content())
    assert out["coingecko_trending_searches"][0]["symbol"] == "PEPE"
    assert out["dexscreener_paid_boosts"][0]["boost_amount"] == 500
    assert out["errors"] == []


async def test_market_overview():
    tool = MarketOverviewTool(
        fake_client_factory({"/api/v3/coins/markets": [{"id": "dogecoin", "current_price": 0.4, "junk": 1}]})
    )
    out = json.loads((await tool.run({"category": "meme-token"})).get_text_content())
    assert out["coins"][0]["id"] == "dogecoin" and "junk" not in out["coins"][0]
