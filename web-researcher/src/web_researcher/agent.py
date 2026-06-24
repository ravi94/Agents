"""LangGraph ReAct agent assembly."""

from __future__ import annotations

from langchain_ollama import ChatOllama
from langgraph.prebuilt import create_react_agent

from web_researcher.config import Settings
from web_researcher.prompts import SYSTEM_PROMPT
from web_researcher.tools import (
    make_fetch_tool,
    make_search_tool,
    make_summarize_tool,
)


def build_agent(settings: Settings):
    """Build a ReAct agent wired to local Ollama + SearXNG tools."""
    llm = ChatOllama(
        model=settings.ollama_model,
        base_url=settings.ollama_host,
        temperature=0.2,
    )

    tools = [
        make_search_tool(settings),
        make_fetch_tool(settings),
        make_summarize_tool(settings),
    ]

    agent = create_react_agent(
        model=llm,
        tools=tools,
        prompt=SYSTEM_PROMPT,
    )
    return agent
