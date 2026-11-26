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


# ------------------------------------------------------------------ second opinion


def test_critic_message_contains_question_and_report():
    from meme_crypto_agent.critic import CRITIC_INSTRUCTIONS, build_critic_message

    msg = build_critic_message("Research WIF", "**Snapshot** WIF at $1.23")
    assert "<question>" in msg and "Research WIF" in msg
    assert "<report>" in msg and "$1.23" in msg
    for heading in ("Verdict", "Numbers Check", "Missed or Softened Red Flags", "Strongest Counter-Argument"):
        assert heading in CRITIC_INSTRUCTIONS


def test_agents_import_and_share_second_opinion():
    from meme_crypto_agent import agent, run_local

    assert agent.SECOND_OPINION in (True, False)
    assert callable(run_local.research)


async def test_research_runs_critic_on_report_and_skips_on_refusal(monkeypatch):
    from meme_crypto_agent import run_local

    calls = []

    async def fake_run(client, system, content):
        calls.append((system, content))
        return "REPORT" if len(calls) == 1 else "REVIEW"

    monkeypatch.setenv("ANTHROPIC_API_KEY", "dummy")
    monkeypatch.setattr(run_local, "_run", fake_run)
    out = await run_local.research("Research WIF")
    assert out.startswith("REPORT") and "## Second Opinion" in out and out.endswith("REVIEW")
    assert "REPORT" in calls[1][1] and "Research WIF" in calls[1][1]  # critic sees question + report

    calls.clear()

    async def refused(client, system, content):
        calls.append(1)
        return "The model declined this request."

    monkeypatch.setattr(run_local, "_run", refused)
    assert "Second Opinion" not in await run_local.research("x")
    assert len(calls) == 1


# ------------------------------------------------------------------ WalletWatch

import pytest  # noqa: E402

from meme_crypto_agent.wallet import WalletWatchTool, build_portfolio, looks_like_secret, validate_address  # noqa: E402

WALLET = "BEmX1nfeZT5i4VpSEeZmhiYxpZ9z4Y1LQLjAtPR9c3re"
SOL_MINT = "So11111111111111111111111111111111111111112"


def test_secret_detection():
    seed = "abandon ability able about above absent absorb abstract absurd abuse access accident"
    assert looks_like_secret(seed)
    assert looks_like_secret(f"here is my wallet\n{seed}\nthanks")
    assert looks_like_secret("4" * 88)
    assert looks_like_secret("[" + ",".join(["12"] * 64) + "]")
    # normal questions and public addresses must pass
    assert not looks_like_secret("what meme coins are trending right now on solana and base today please")
    assert not looks_like_secret(f"Check my wallet {WALLET}")
    assert not looks_like_secret("Research DezXAZ8z7PnrnRJjz3wXBoRgixCa6xjnB7YaB1pPB263")


def test_validate_address():
    assert validate_address(f"  {WALLET} ") == WALLET
    with pytest.raises(Exception, match="recovery phrase"):
        validate_address("abandon ability able about above absent absorb abstract absurd abuse access accident")
    with pytest.raises(Exception, match="Not a valid"):
        validate_address("0xabc")


def test_build_portfolio_values_alerts_and_spam():
    pairs = {
        SOL_MINT: pair(baseToken={"address": SOL_MINT, "symbol": "SOL"}, priceUsd="100"),
        "MEME": pair(baseToken={"address": "MEME", "symbol": "MEME"}, priceUsd="2"),
        "RUG": pair(
            baseToken={"address": "RUG", "symbol": "RUG"}, priceUsd="1", liquidity={"usd": 3000},
            pairCreatedAt=time.time() * 1000 - HOUR, txns={"h24": {"buys": 200, "sells": 0}}, info={},
        ),
        "DUST": pair(baseToken={"address": "DUST", "symbol": "DUST"}, priceUsd="0.0001"),
    }
    holdings = {"MEME": 300, "RUG": 50, "DUST": 10, "AIRDROP1": 1_000_000}
    r = build_portfolio(sol=1, holdings=holdings, pairs=pairs, min_value_usd=1, limit=10)

    assert r["sol_value_usd"] == 100 and r["total_value_usd"] == 100 + 600 + 50
    assert [p["symbol"] for p in r["positions"]] == ["MEME", "RUG"]  # sorted, dust hidden
    assert r["positions"][0]["portfolio_pct"] == 80.0
    assert r["unpriced_token_count"] == 1
    text = " ".join(r["alerts"])
    assert "concentration" in text and "RUG" in text and "airdrop" in text


async def test_wallet_tool_end_to_end_with_fake_rpc():
    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "POST":
            body = json.loads(request.content)
            if body["method"] == "getBalance":
                return httpx.Response(200, json={"result": {"value": 2_000_000_000}})
            token_2022 = body["params"][1]["programId"].startswith("Tokenz")
            acct = {"account": {"data": {"parsed": {"info": {"mint": "MEME", "tokenAmount": {"uiAmount": 10}}}}}}
            return httpx.Response(200, json={"result": {"value": [] if token_2022 else [acct]}})
        return httpx.Response(200, json=[
            pair(baseToken={"address": SOL_MINT, "symbol": "SOL"}, priceUsd="50"),
            pair(baseToken={"address": "MEME", "symbol": "MEME"}, priceUsd="3"),
        ])

    tool = WalletWatchTool(lambda: httpx.AsyncClient(transport=httpx.MockTransport(handler)))
    out = json.loads((await tool.run({"address": WALLET})).get_text_content())
    assert out["sol_balance"] == 2 and out["total_value_usd"] == 130
    assert out["positions"][0]["symbol"] == "MEME" and "rugcheck" in out["positions"][0]["verify_links"]
