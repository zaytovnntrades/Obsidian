# Meme & Crypto Research Agent (Agent Stack starter)

A research assistant for meme coins and crypto, built on [Agent Stack](https://github.com/i-am-bee/agentstack).
Give it a ticker, a contract address, or ask "what's trending?". It pulls live on-chain data, runs a
**red-flag scorer**, searches the news, and writes a structured report.

> Research only, not financial advice. Most meme coins go to zero.

## What it can do

| Tool | Source (free, no signup) | Use it for |
|---|---|---|
| `TokenLookup` | DexScreener | Any DEX token: price, liquidity, volume, buys/sells, age, socials, **risk score**, verify links |
| `TrendingRadar` | CoinGecko trending + DexScreener boosts | Idea generation: organic attention vs. *paid* promotion |
| `MarketOverview` | CoinGecko markets | BTC/ETH/SOL context, top meme coins (`category="meme-token"`) |
| `DuckDuckGo` | Web search | Narrative, news, listings, exploits |
| `ThinkTool` | (none) | Lets the model plan before answering |

Every report uses the same headings: **Snapshot → Liquidity & Flow → Red Flags → Narrative → Bull/Bear → Before You Touch It**.

## Quickstart (about 10 minutes)

```bash
# 1. Install Agent Stack (Linux/macOS) and pick an LLM provider when asked
sh -c "$(curl -LsSf https://agentstack.beeai.dev/install.sh)"

# 2. Run this agent
cd meme-crypto-agent
uv run server

# 3. In another terminal
agentstack run meme_crypto_research "What meme coins are trending right now?"
agentstack run meme_crypto_research "Research BONK on Solana"
agentstack ui      # or chat with it in the browser
```

### No platform? Run it straight from the terminal
`run_local.py` uses the same tools and analyst prompt, with Claude via the official Anthropic SDK
(plus Claude's built-in web search instead of DuckDuckGo):
```bash
export ANTHROPIC_API_KEY=sk-ant-...      # console.anthropic.com
uv run research "What meme coins are trending right now?"
```

Optional: set `COINGECKO_API_KEY` (free "Demo" key at coingecko.com/api) for higher rate limits.

Run the offline tests (no network or LLM needed): `uv run pytest`

## Second-opinion mode (on by default)
After the research report, a second pass with an adversarial brief (`critic.py`) re-checks the numbers
with the same tools, hunts for missed red flags, and argues the other side. It ends with a **Verdict**
(AGREE / PARTLY AGREE / DISAGREE). When the two passes disagree, slow down: that's your signal.

- Terminal: `uv run research --no-second-opinion "..."` skips it.
- Agent Stack: set `SECOND_OPINION=false` to skip it.
- Cost: roughly doubles tokens per question. Worth it before money moves; skip it for quick lookups.

## The red-flag scorer (`src/meme_crypto_agent/risk.py`)

This is your rulebook as code. Each rule adds points; 0–29 = LOWER, 30–59 = ELEVATED, 60+ = HIGH.

| Signal | Why it matters | Points |
|---|---|---|
| Liquidity < $10k / < $50k | A few wallets can crater the price | +30 / +15 |
| Pair < 24h / < 7 days old | Most rugs happen on day one | +25 / +10 |
| FDV > 50× liquidity | Valuation has no exit depth | +15 |
| 24h volume > 10× liquidity | Wash trading / bot churn | +10 |
| Many buys, **0 sells** | Honeypot signature: you can buy, you can't sell | +25 |
| Sells > 5× buys (100+ sells) | Heavy dumping | +30 |
| Sells > 2× buys | Distribution / selling pressure | +10 |
| +300% in 24h | You'd be buying after the move | +10 |
| No website or socials | Low-effort launch | +10 |

**High-ROI hack:** edit the constants at the top of `risk.py` to match *your* rules (e.g. "I never touch
anything under $100k liquidity"). The agent then enforces your discipline on every coin, every time.

The scorer **cannot** see contract code, mint/freeze authority, or holder concentration. That's why each
token comes with `verify_links`: RugCheck (Solana), Honeypot.is + TokenSniffer (EVM), Bubblemaps (holders).

## Learning path: apprentice to master

**Stage 1: Run it.** Do the Quickstart. Ask about 3 coins you know and compare the reports to what you already believe.

**Stage 2: Read the code (in this order).**
1. `data.py`: raw API calls. Open the URLs in your browser to see the real JSON.
2. `risk.py`: turning numbers into judgment.
3. `tools.py`: how a Python function becomes something the LLM can call (`name`, `description`, `input_schema`, `_run`).
4. `agent.py`: the instructions (the analyst's personality and report format) and the streaming loop.

**Stage 3: Customize. Pick one task.**
- Change the thresholds in `risk.py` to your rules.
- Add a chain filter default (e.g. always `solana`).
- Change the report headings in `INSTRUCTIONS`.

**Stage 4: Add a superpower.** Copy a pattern from Agent Stack's `apps/agentstack-sdk-py/examples/`:
- *Secrets extension* (`secrets_agent.py`): let users paste a Birdeye / Helius / Etherscan key at runtime.
- *Form extension* (`form_agent.py`): a "research request" form with chain, budget, and risk tolerance.
- *Citations* (`citation_agent.py`): clickable sources in the UI.
- New tool ideas: holder concentration (Birdeye / Helius), contract checks (GoPlus Security API, free),
  Fear & Greed index (alternative.me, free), Reddit or X mentions.

**Stage 5: Ship it.** Push to GitHub, then deploy into Agent Stack with:
```bash
agentstack add "https://github.com/<you>/<repo>@<branch>#path=/meme-crypto-agent"
```

## Shortcuts and uncommon resources
- **DexScreener API** (docs.dexscreener.com): free, no key, covers every chain. Best free meme data source.
- **GoPlus Security API** (gopluslabs.io): free token-security checks (honeypot, owner privileges, taxes). A natural next tool.
- **CoinGecko `meme-token` category**: one call gives you the whole meme sector ranked by market cap.
- **Boosts ≠ demand.** DexScreener boosts are paid ads. A token that is trending on CoinGecko *without* boosts is the more interesting signal.
- **Ticker collisions.** Dozens of tokens share popular tickers. The agent warns you when it sees copycats, so always confirm the contract address.

## Version pins (why they exist)
`agentstack-sdk 0.7.1` (PyPI) breaks with `mcp>=2` and with `fastapi>=0.140`, so both are pinned in
`pyproject.toml`. `beeai-framework` is pinned to `0.1.78`, the version Agent Stack's own agents use.
