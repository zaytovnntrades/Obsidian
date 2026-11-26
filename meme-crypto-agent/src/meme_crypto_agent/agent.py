"""Meme & Crypto Research agent for Agent Stack.

Run locally:   uv run server          (then: agentstack run meme_crypto_research "Research WIF")
"""

from __future__ import annotations

import os
from textwrap import dedent
from typing import Annotated

from a2a.types import AgentSkill, Message, Role
from a2a.utils.message import get_message_text
from agentstack_sdk.a2a.extensions import (
    AgentDetail,
    AgentDetailTool,
    ErrorExtensionParams,
    ErrorExtensionServer,
    ErrorExtensionSpec,
    LLMServiceExtensionServer,
    LLMServiceExtensionSpec,
    TrajectoryExtensionServer,
    TrajectoryExtensionSpec,
)
from agentstack_sdk.a2a.types import AgentMessage
from agentstack_sdk.server import Server
from agentstack_sdk.server.context import RunContext
from beeai_framework.adapters.agentstack.backend.chat import AgentStackChatModel
from beeai_framework.agents.requirement import RequirementAgent
from beeai_framework.agents.requirement.events import (
    RequirementAgentFinalAnswerEvent,
    RequirementAgentSuccessEvent,
)
from beeai_framework.agents.requirement.utils._tool import FinalAnswerTool
from beeai_framework.backend import AssistantMessage, ChatModelParameters, UserMessage
from beeai_framework.errors import FrameworkError
from beeai_framework.tools.search.duckduckgo import DuckDuckGoSearchTool
from beeai_framework.tools.think import ThinkTool

from meme_crypto_agent.critic import CRITIC_INSTRUCTIONS, build_critic_message
from meme_crypto_agent.tools import MarketOverviewTool, TokenLookupTool, TrendingTool

INSTRUCTIONS = dedent(
    """\
    You are a skeptical crypto research analyst who specialises in meme coins. Your job is to help the user
    do fast, disciplined research - NOT to hype coins or tell them what to buy.

    ## Workflow
    1. Specific token? -> call TokenLookup first. If several different contract addresses share the ticker,
       say so and analyse the one with the most liquidity unless the user gave an address.
    2. "What's hot / find ideas"? -> call TrendingRadar, then TokenLookup on the 2-3 most interesting.
    3. Majors or market context (BTC, ETH, SOL, top memes)? -> MarketOverview (category 'meme-token' for memes).
    4. Use DuckDuckGo for narrative: news, launches, listings, influencer/KOL mentions, exploits.
    5. Never invent numbers. If a tool failed, say which data is missing.

    ## Report format (use these headings)
    **Snapshot** - name, ticker, chain, price, market cap/FDV, 24h change, DexScreener link.
    **Liquidity & Flow** - liquidity, 24h volume, buys vs sells, pair age.
    **Red Flags** - the risk score + level and every flag, in plain English. Never water these down.
    **Narrative** - why people care (or don't), with cited sources as [text](url).
    **Bull Case / Bear Case** - 2-3 bullets each.
    **Before You Touch It** - the verify_links (holder concentration, honeypot/rug checks) plus a reminder to
    size small, use a separate hot wallet, and decide your exit before entry.

    End every research answer with: "Research only - not financial advice. Most meme coins go to zero."
    """
)

SECOND_OPINION = os.getenv("SECOND_OPINION", "true").lower() == "true"

server = Server()


@server.agent(
    name="Meme & Crypto Research",
    version="0.1.0",
    default_input_modes=["text", "text/plain"],
    default_output_modes=["text", "text/plain"],
    detail=AgentDetail(
        interaction_mode="multi-turn",
        user_greeting="Give me a ticker, contract address, or ask what's trending.",
        tools=[
            AgentDetailTool(name="TokenLookup", description="DexScreener pair data + automatic red-flag score."),
            AgentDetailTool(name="TrendingRadar", description="CoinGecko trending searches + DexScreener boosts."),
            AgentDetailTool(name="MarketOverview", description="CoinGecko market data for majors & meme sector."),
            AgentDetailTool(name="DuckDuckGo", description="News and narrative search."),
        ],
        framework="BeeAI",
        programming_language="Python",
    ),
    skills=[
        AgentSkill(
            id="meme-crypto-research",
            name="Meme & crypto research",
            description="Researches meme coins and crypto tokens, scores red flags, and writes a structured report.",
            tags=["crypto", "memecoin", "research", "defi"],
            examples=[
                "Research BONK on Solana",
                "What meme coins are trending right now?",
                "Check this contract: 0x6982508145454ce325ddbe47a25d4ec3d2311933",
                "Compare DOGE, SHIB and PEPE",
            ],
        )
    ],
)
async def meme_crypto_research(
    input: Message,
    context: RunContext,
    trajectory: Annotated[TrajectoryExtensionServer, TrajectoryExtensionSpec()],
    llm_ext: Annotated[LLMServiceExtensionServer, LLMServiceExtensionSpec.single_demand()],
    _e: Annotated[ErrorExtensionServer, ErrorExtensionSpec(ErrorExtensionParams(include_stacktrace=True))],
):
    """Researches meme coins and crypto tokens with live DEX + market data and a red-flag scorer."""
    await context.store(input)
    history = [m async for m in context.load_history() if isinstance(m, Message) and m.parts]
    messages = [
        UserMessage(get_message_text(m)) if m.role == Role.user else AssistantMessage(get_message_text(m))
        for m in history
        if get_message_text(m)
    ]

    llm = AgentStackChatModel(parameters=ChatModelParameters(stream=True))
    llm.set_context(llm_ext)

    def make_agent(instructions: str) -> RequirementAgent:
        tools = [TokenLookupTool(), TrendingTool(), MarketOverviewTool(), DuckDuckGoSearchTool(), ThinkTool()]
        return RequirementAgent(llm=llm, tools=tools, instructions=instructions)

    async def run_pass(agent: RequirementAgent, pass_messages, result: list[str]):
        """Stream one agent pass; append its final text to `result`."""
        try:
            async for event, _meta in agent.run(pass_messages):
                match event:
                    case RequirementAgentFinalAnswerEvent(delta=delta):
                        yield delta
                    case RequirementAgentSuccessEvent(state=state):
                        if state.answer:
                            result[:] = [state.answer.text]
                        step = state.steps[-1]
                        if step.tool and step.tool.name != FinalAnswerTool.name:
                            yield trajectory.trajectory_metadata(title=step.tool.name, content=str(step.input)[:500])
        except FrameworkError as err:
            raise RuntimeError(err.explain()) from err

    report: list[str] = []
    async for chunk in run_pass(make_agent(INSTRUCTIONS), messages, report):
        yield chunk
    full_text = report[0] if report else ""

    if report and SECOND_OPINION:
        question = get_message_text(input)
        divider = "\n\n---\n\n## Second Opinion\n\n"
        yield divider
        review: list[str] = []
        critic_messages = [UserMessage(build_critic_message(question, report[0]))]
        async for chunk in run_pass(make_agent(CRITIC_INSTRUCTIONS), critic_messages, review):
            yield chunk
        if review:
            full_text += divider + review[0]

    if full_text:
        await context.store(AgentMessage(text=full_text))


def serve() -> None:
    kwargs = {}
    if os.getenv("PLATFORM_CONTEXT_STORE", "true").lower() == "true":
        from agentstack_sdk.server.store.platform_context_store import PlatformContextStore

        kwargs["context_store"] = PlatformContextStore()
    server.run(host=os.getenv("HOST", "127.0.0.1"), port=int(os.getenv("PORT", 8000)), **kwargs)


if __name__ == "__main__":
    serve()
