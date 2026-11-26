"""WalletWatch: read-only Solana portfolio check from a PUBLIC address.

Never asks for or handles seed phrases / private keys. A public address can only be read, never spent from.
"""

from __future__ import annotations

import re
from typing import Any

import httpx
from beeai_framework.context import RunContext
from beeai_framework.tools import JSONToolOutput, ToolRunOptions
from beeai_framework.tools.errors import ToolInputValidationError
from pydantic import BaseModel, Field

from meme_crypto_agent import data
from meme_crypto_agent.risk import score_pair
from meme_crypto_agent.tools import _BaseTool, verify_links

BASE58 = re.compile(r"^[1-9A-HJ-NP-Za-km-z]{32,44}$")
CONCENTRATION_PCT = 50  # one coin above this share of the portfolio gets flagged
SEED_WORDS = re.compile(r"^(?:[a-z]+\s+){11,23}[a-z]+$")
# A line that is ONLY 12/15/18/21/24 lowercase words, or an 87-88 char base58 string (exported private key).
_SEED_LINE = re.compile(r"^[ \t]*((?:[a-z]{3,8}[ \t]+){11,23}[a-z]{3,8})[ \t]*$", re.MULTILINE)
_PRIVATE_KEY = re.compile(r"(?<![1-9A-HJ-NP-Za-km-z])[1-9A-HJ-NP-Za-km-z]{86,88}(?![1-9A-HJ-NP-Za-km-z])")
_KEY_ARRAY = re.compile(r"\[\s*(?:\d{1,3}\s*,\s*){63}\d{1,3}\s*\]")  # 64-byte keypair JSON

SECRET_WARNING = (
    "STOP: that message looks like it contains a wallet recovery phrase or private key, so it was NOT sent "
    "anywhere. Anyone who has it can empty your wallet. If you pasted it somewhere else too, create a new "
    "wallet and move your funds now. To check a wallet, share only its PUBLIC address."
)


def looks_like_secret(text: str) -> bool:
    for line in _SEED_LINE.findall(text):
        if len(line.split()) in (12, 15, 18, 21, 24):
            return True
    return bool(_PRIVATE_KEY.search(text) or _KEY_ARRAY.search(text))


def validate_address(address: str) -> str:
    address = address.strip()
    if SEED_WORDS.match(address.lower()):
        raise ToolInputValidationError(
            "That looks like a recovery phrase. NEVER share it - anyone with it can empty the wallet. "
            "Move funds to a new wallet if it was exposed. WalletWatch only needs the PUBLIC address."
        )
    if not BASE58.match(address):
        raise ToolInputValidationError("Not a valid Solana address (expected 32-44 base58 characters).")
    return address


def build_portfolio(
    sol: float, holdings: dict[str, float], pairs: dict[str, dict[str, Any]], min_value_usd: float, limit: int
) -> dict[str, Any]:
    sol_pair = pairs.get(data.WRAPPED_SOL_MINT)
    sol_price = float(sol_pair["priceUsd"]) if sol_pair and sol_pair.get("priceUsd") else None

    positions: list[dict[str, Any]] = []
    unpriced: list[str] = []
    for mint, amount in holdings.items():
        pair = pairs.get(mint)
        price = float(pair["priceUsd"]) if pair and pair.get("priceUsd") else None
        if price is None:
            unpriced.append(mint)
            continue
        value = amount * price
        if value < min_value_usd:
            continue
        base = pair.get("baseToken") or {}
        positions.append(
            {
                "symbol": base.get("symbol"),
                "name": base.get("name"),
                "mint": mint,
                "amount": amount,
                "price_usd": price,
                "value_usd": round(value, 2),
                "change_24h_pct": (pair.get("priceChange") or {}).get("h24"),
                "liquidity_usd": (pair.get("liquidity") or {}).get("usd"),
                "risk": score_pair(pair).as_dict(),
                "dexscreener_url": pair.get("url"),
                "verify_links": verify_links("solana", mint),
            }
        )

    sol_value = round(sol * sol_price, 2) if sol_price else None
    total = (sol_value or 0) + sum(p["value_usd"] for p in positions)
    positions.sort(key=lambda p: p["value_usd"], reverse=True)
    for p in positions:
        p["portfolio_pct"] = round(100 * p["value_usd"] / total, 1) if total else None

    alerts = []
    for p in positions:
        if p["portfolio_pct"] and p["portfolio_pct"] > CONCENTRATION_PCT:
            alerts.append(f"{p['symbol']} is {p['portfolio_pct']}% of the portfolio - concentration risk")
        if p["risk"]["level"] == "HIGH":
            alerts.append(f"{p['symbol']} (${p['value_usd']:,.0f}) scores HIGH risk: " + "; ".join(p["risk"]["flags"][:3]))
    if unpriced:
        alerts.append(
            f"{len(unpriced)} token(s) have no DEX price - often dust or scam airdrops. Do NOT interact with "
            "unknown airdropped tokens or visit links in their names."
        )

    return {
        "sol_balance": round(sol, 6),
        "sol_value_usd": sol_value,
        "total_value_usd": round(total, 2),
        "positions": positions[:limit],
        "positions_hidden": max(0, len(positions) - limit),
        "unpriced_token_count": len(unpriced),
        "alerts": alerts,
    }


class WalletWatchInput(BaseModel):
    address: str = Field(description="PUBLIC Solana wallet address (base58). Never a seed phrase or private key.")
    min_value_usd: float = Field(default=1.0, ge=0, description="Hide positions worth less than this (dust).")
    limit: int = Field(default=25, ge=1, le=100, description="Max positions to return, largest first.")


class WalletWatchTool(_BaseTool):
    name = "WalletWatch"
    description = (
        "Read-only Solana portfolio check from a PUBLIC wallet address (e.g. a Phantom address): SOL balance, "
        "every token with live price and USD value, portfolio share, a red-flag risk score per holding, and "
        "alerts (concentration, high-risk holdings, scam airdrops). Use when the user gives a wallet address or "
        "asks about 'my wallet/portfolio/bags'."
    )
    input_schema = WalletWatchInput

    async def _run(
        self, input: WalletWatchInput, options: ToolRunOptions | None, context: RunContext
    ) -> JSONToolOutput[dict[str, Any]]:
        address = validate_address(input.address)
        async with self._client_factory() as client:
            try:
                sol = await data.solana_balance_sol(client, address)
                holdings = await data.solana_token_holdings(client, address)
            except httpx.HTTPError as e:
                raise ToolInputValidationError(
                    f"Could not read the wallet ({e}). The public Solana RPC is rate-limited; retry shortly or "
                    "set SOLANA_RPC_URL to a free Helius/QuickNode endpoint."
                ) from e
            pairs = await data.dex_best_pairs(client, "solana", [data.WRAPPED_SOL_MINT, *holdings])
        result = build_portfolio(sol, holdings, pairs, input.min_value_usd, input.limit)
        result["address"] = address
        return JSONToolOutput(result)
