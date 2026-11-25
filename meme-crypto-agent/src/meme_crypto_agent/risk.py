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


def score_pair(pair: dict[str, Any], now_ms: float | None = None) -> RiskReport:
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
            flags.append(f"Brand-new pair ({age_h:.1f}h old) - most rugs happen in the first day")
        elif age_h < YOUNG_PAIR_DAYS * 24:
            score += 10
            flags.append(f"Young pair ({age_h / 24:.1f} days old)")
        else:
            positives.append(f"Pair has survived {age_h / 24:.0f} days")
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


def summarize_pair(pair: dict[str, Any]) -> dict[str, Any]:
    """Compact, LLM-friendly view of a DexScreener pair plus its risk report."""
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
        "liquidity_usd": (pair.get("liquidity") or {}).get("usd"),
        "fdv": pair.get("fdv"),
        "market_cap": pair.get("marketCap"),
        "txns_24h": (pair.get("txns") or {}).get("h24"),
        "pair_created_at_ms": pair.get("pairCreatedAt"),
        "paid_boosts_active": (pair.get("boosts") or {}).get("active"),
        "websites": [w.get("url") for w in info.get("websites") or []],
        "socials": [s.get("url") for s in info.get("socials") or []],
        "dexscreener_url": pair.get("url"),
        "risk": score_pair(pair).as_dict(),
    }
