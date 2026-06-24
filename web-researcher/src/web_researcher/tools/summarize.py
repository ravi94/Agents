"""Cheap focused-summary tool — used to compress long pages."""

from __future__ import annotations

from langchain_core.tools import StructuredTool
from langchain_ollama import ChatOllama
from pydantic import BaseModel, Field

from web_researcher.config import Settings

_SUMMARIZE_PROMPT = (
    "You are a research assistant. Compress the following page text into a tight, "
    "factual summary focused on this question:\n\n"
    "QUESTION: {focus}\n\n"
    "Rules:\n"
    "- Keep every concrete number, name, date, and quote relevant to the question.\n"
    "- Drop boilerplate, marketing fluff, navigation copy.\n"
    "- 200-400 words. No preamble. No 'this article discusses' — just the facts.\n\n"
    "TEXT:\n{text}"
)


class SummarizeInput(BaseModel):
    text: str = Field(..., description="The text to summarize")
    focus: str = Field(
        ...,
        description=(
            "The specific question or angle you want the summary focused on. "
            "Be precise — the summarizer keeps only what's relevant to this."
        ),
    )


def make_summarize_tool(settings: Settings) -> StructuredTool:
    llm = ChatOllama(
        model=settings.ollama_summarizer_model,
        base_url=settings.ollama_host,
        temperature=0.1,
    )

    def _summarize(text: str, focus: str) -> str:
        prompt = _SUMMARIZE_PROMPT.format(focus=focus, text=text)
        result = llm.invoke(prompt)
        # ChatOllama returns an AIMessage; .content is str or list[dict]
        content = result.content
        if isinstance(content, list):
            content = "".join(
                part.get("text", "") if isinstance(part, dict) else str(part)
                for part in content
            )
        return str(content).strip()

    return StructuredTool.from_function(
        func=_summarize,
        name="summarize_chunk",
        description=(
            "Compress a long block of page text into a focused factual summary. "
            "Use this when fetch_page returned 'truncated': true, or when you want "
            "to keep your working context lean. Provide a clear 'focus' question."
        ),
        args_schema=SummarizeInput,
    )
