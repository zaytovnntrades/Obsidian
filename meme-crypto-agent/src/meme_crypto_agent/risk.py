"""Transparent red-flag scorer for DEX pairs.

This is a *screening* heuristic, not a safety check. It turns the raw numbers a
DexScreener pair gives you into plain-English flags so you can kill bad ideas fast.
Higher score = more red flags. Tweak the thresholds below to match your own rules.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any

# --- Your rulebook. Edit these to encode your own trading rules. -------------
MIN_LIQUIDITY_USD = 50_000  # below this, a few wallets can move price massively
DANGER_LIQUIDITY_USD = 10_000
NEW_PAIR_HOURS = 24
YOUNG_PAIR_DAYS = 7
MAX_FDV_TO_LIQUIDITY = 50  # huge valuation vs. thin pool = easy to dump on you
MAX_VOLUME_TO_LIQUIDITY = 10  # extreme turnover can mean wash trading / bot churn
PUMP_24H_PCT = 300


@dataclass
class RiskReport:
    score: int
    level: str
    flags: list[str] = field(default_factory=list)
    positives: list[str] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return {"score": self.score, "level": self.level, "flags": self.flags, "positives": self.positives}


def _num(value: Any) -> float | None:
    try:
        return float(value) if value is not None else None
    except (TypeError, ValueError):
        return None


POOL_CAP = 30  # DexScreener returns at most this many pools per token


def aggregate_pools(pools: list[dict[str, Any]], token_address: str) -> dict[str, Any] | None:
    """Totals across every pool that trades `token_address`.

    A big coin trades in dozens of pools; judging it by one pool understates liquidity and can
    even pick the wrong "main" pool. Liquidity and volume count every pool the token is in.
    Buy/sell counts only use pools where the token is the BASE asset (in a pool where it is the
    quote, a "buy" means buying the other token, i.e. selling this one).
    """
    def base_of(p): return (p.get("baseToken") or {}).get("address")
    def quote_of(p): return (p.get("quoteToken") or {}).get("address")
    def liq(p): return _num((p.get("liquidity") or {}).get("usd")) or 0

    own = [p for p in pools if token_address in (base_of(p), quote_of(p))]
    if not own:
        return None
    as_base = [p for p in own if base_of(p) == token_address]
    flow = [((p.get("txns") or {}).get("h24") or {}) for p in as_base]
    created = [c for c in (_num(p.get("pairCreatedAt")) for p in own) if c]
    top = max(as_base or own, key=liq)
    return {
        "pool_count": len(own),
        "dex_count": len({p.get("dexId") for p in own}),
        "liquidity_usd": round(sum(liq(p) for p in own), 2),
        "top_pool_liquidity_usd": round(liq(top), 2),
        "volume_h24": round(sum(_num((p.get("volume") or {}).get("h24")) or 0 for p in own), 2),
        "buys_h24": sum(int(f.get("buys") or 0) for f in flow),
        "sells_h24": sum(int(f.get("sells") or 0) for f in flow),
        "oldest_pair_created_ms": min(created) if created else None,
        "capped": len(pools) >= POOL_CAP,
        "top_pool": top,
    }


def score_pair(pair: dict[str, Any], now_ms: float | None = None, totals: dict[str, Any] | None = None) -> RiskReport:
    """Score one pair, or - with `totals` from aggregate_pools - the token across all its pools."""
    now_ms = now_ms if now_ms is not None else time.time() * 1000
    score = 0
    flags: list[str] = []
    positives: list[str] = []

    liquidity = _num((pair.get("liquidity") or {}).get("usd"))
    fdv = _num(pair.get("fdv")) or _num(pair.get("marketCap"))
    volume24 = _num((pair.get("volume") or {}).get("h24"))
    change24 = _num((pair.get("priceChange") or {}).get("h24"))
    txns24 = (pair.get("txns") or {}).get("h24") or {}
    buys, sells = int(txns24.get("buys") or 0), int(txns24.get("sells") or 0)
    created = _num(pair.get("pairCreatedAt"))
    info = pair.get("info") or {}
    if totals:
        liquidity = totals["liquidity_usd"]
        volume24 = totals["volume_h24"]
        buys, sells = totals["buys_h24"], totals["sells_h24"]
        created = totals["oldest_pair_created_ms"] or created
        if totals["pool_count"] > 1:
            more = "+" if totals.get("capped") else ""
            positives.append(f"Liquidity across {totals['pool_count']}{more} pools on {totals['dex_count']} DEXes")

    # Liquidity
    if liquidity is None:
        score += 25
        flags.append("No liquidity data reported")
    elif liquidity < DANGER_LIQUIDITY_USD:
        score += 30
        flags.append(f"Very thin liquidity (${liquidity:,.0f}) - tiny sells move price hard")
    elif liquidity < MIN_LIQUIDITY_USD:
        score += 15
        flags.append(f"Low liquidity (${liquidity:,.0f})")
    else:
        positives.append(f"Liquidity ${liquidity:,.0f}")

    # Age
    if created:
        age_h = (now_ms - created) / 3_600_000
        if age_h < NEW_PAIR_HOURS:
            score += 25
            flags.append(f"Brand-new token ({age_h:.1f}h since first pool) - most rugs happen in the first day")
        elif age_h < YOUNG_PAIR_DAYS * 24:
            score += 10
            flags.append(f"Young token ({age_h / 24:.1f} days since first pool)")
        else:
            positives.append(f"Trading for {age_h / 24:.0f} days")
    else:
        score += 5
        flags.append("Unknown pair age")

    # Valuation vs. pool depth
    if fdv and liquidity:
        ratio = fdv / liquidity
        if ratio > MAX_FDV_TO_LIQUIDITY:
            score += 15
            flags.append(f"FDV is {ratio:.0f}x liquidity - exit liquidity is shallow")

    # Turnover
    if volume24 and liquidity:
        turnover = volume24 / liquidity
        if turnover > MAX_VOLUME_TO_LIQUIDITY:
            score += 10
            flags.append(f"24h volume is {turnover:.0f}x liquidity - possible wash trading / bot churn")

    # Order flow (honeypot hint: lots of buys, nobody able to sell)
    if buys > 50 and sells == 0:
        score += 25
        flags.append(f"{buys} buys and 0 sells in 24h - classic honeypot signature")
    elif sells > 100 and sells > 5 * buys:
        score += 30
        flags.append(f"Heavy dumping: {sells} sells vs {buys} buys in 24h ({sells / max(buys, 1):.0f}:1)")
    elif sells and buys < 0.5 * sells:
        score += 10
        flags.append(f"Sellers dominate 24h flow ({buys} buys vs {sells} sells)")
    elif buys + sells > 0:
        positives.append(f"24h flow {buys} buys / {sells} sells")

    # Chasing a pump
    if change24 is not None and change24 > PUMP_24H_PCT:
        score += 10
        flags.append(f"Up {change24:,.0f}% in 24h - you'd be buying after the move")

    # Presence
    if not info.get("websites") and not info.get("socials"):
        score += 10
        flags.append("No website or socials listed")
    else:
        positives.append("Has website/socials listed")

    score = min(score, 100)
    level = "LOWER" if score < 30 else "ELEVATED" if score < 60 else "HIGH"
    return RiskReport(score=score, level=level, flags=flags, positives=positives)


def summarize_pair(pair: dict[str, Any], totals: dict[str, Any] | None = None) -> dict[str, Any]:
    """Compact, LLM-friendly view of a token: its main (most liquid) pool, all-pool totals, and risk."""
    if totals:
        pair = totals["top_pool"]
    base = pair.get("baseToken") or {}
    info = pair.get("info") or {}
    return {
        "name": base.get("name"),
        "symbol": base.get("symbol"),
        "token_address": base.get("address"),
        "chain": pair.get("chainId"),
        "dex": pair.get("dexId"),
        "quote": (pair.get("quoteToken") or {}).get("symbol"),
        "price_usd": pair.get("priceUsd"),
        "price_change_pct": pair.get("priceChange"),
        "volume_usd": pair.get("volume"),
        "liquidity_usd": totals["liquidity_usd"] if totals else (pair.get("liquidity") or {}).get("usd"),
        "pools": (
            {k: totals[k] for k in ("pool_count", "dex_count", "top_pool_liquidity_usd", "volume_h24",
                                    "buys_h24", "sells_h24", "capped")}
            if totals else {"pool_count": 1, "note": "single pool only - totals unavailable"}
        ),
        "fdv": pair.get("fdv"),
        "market_cap": pair.get("marketCap"),
        "txns_24h": (pair.get("txns") or {}).get("h24"),
        "pair_created_at_ms": pair.get("pairCreatedAt"),
        "paid_boosts_active": (pair.get("boosts") or {}).get("active"),
        "websites": [w.get("url") for w in info.get("websites") or []],
        "socials": [s.get("url") for s in info.get("socials") or []],
        "dexscreener_url": pair.get("url"),
        "risk": score_pair(pair, totals=totals).as_dict(),
    }
