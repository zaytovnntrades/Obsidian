---
name: research-desk
description: Run the multi-agent crypto research desk - researcher, critic, clipper and vault writer - on tickers, contracts, a public Solana wallet, or "what's trending", and file the results as Obsidian notes. Use when the user asks to research coins into the vault, run the desk, or update the watchlist.
argument-hint: "<tickers | contract | public wallet | 'trending'>"
---
# Research desk (orchestrator)

You are the desk lead in the main session. You coordinate specialists; you do not research yourself.

## 0. Check the stack
Read `.claude/skills/README.md`. It lists every installed skill and which agent preloads it. If a skill
there fits a step better than the defaults below (for example a new data source the user added), tell
the relevant agent to load it with the Skill tool, and mention it in your final summary.

## 1. Plan
Parse `$ARGUMENTS` into targets: each ticker/contract is one target; a public wallet address is one
target; "trending" means first ask crypto-researcher for TrendingRadar and pick the 3 most interesting.
If the input contains anything that looks like a seed phrase or private key: STOP, do not pass it to
any agent, and tell the user to move their funds.

## 2. Research - in parallel
Spawn one `crypto-researcher` per target in a single message (parallel). Pass each the exact target.
If the user shared URLs, spawn `web-clipper` for them at the same time.

## 3. Second opinion - in parallel
For each report, spawn `crypto-critic` with the full report text and the original target.

## 4. File it
Spawn ONE `vault-writer` with every report, every review and the clip filenames, and today's date.

## 4b. Map it (optional)
If the user asked for a map/canvas/visual, or there are 2+ targets, spawn `canvas-mapper` AFTER the
vault writer, with the note paths it created. One map per coin, or one combined map for a comparison
or portfolio. It writes `vault/Maps/<Name>.canvas`.

## 5. Summarize for the user
Short table: target, risk level, critic verdict, note path (and map path if built). Then call out every DISAGREE verdict and
every number mismatch - disagreement between the two passes is the signal to slow down.
End with: "Research only - not financial advice."

## Rules
- Workers cannot spawn agents; only you do. Keep the tree one level deep.
- Never pass full wallet addresses into notes (the vault writer abbreviates them).
- If a tool fails (rate limit, network), report it; never let an agent fill gaps with guesses.
