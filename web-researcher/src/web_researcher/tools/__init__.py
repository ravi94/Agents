"""Tools exposed to the ReAct agent.

Imports are intentionally lazy via __getattr__ so that importing one tool
(e.g. for tests) doesn't force-load Ollama for the summarize tool.
"""

from typing import TYPE_CHECKING

__all__ = ["make_search_tool", "make_fetch_tool", "make_summarize_tool"]


def __getattr__(name: str):
    if name == "make_search_tool":
        from web_researcher.tools.search import make_search_tool

        return make_search_tool
    if name == "make_fetch_tool":
        from web_researcher.tools.fetch import make_fetch_tool

        return make_fetch_tool
    if name == "make_summarize_tool":
        from web_researcher.tools.summarize import make_summarize_tool

        return make_summarize_tool
    raise AttributeError(f"module 'web_researcher.tools' has no attribute {name!r}")


if TYPE_CHECKING:  # pragma: no cover
    from web_researcher.tools.fetch import make_fetch_tool
    from web_researcher.tools.search import make_search_tool
    from web_researcher.tools.summarize import make_summarize_tool
