"""Typer CLI with live rich output."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Optional

import typer
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
from rich.console import Console
from rich.markdown import Markdown
from rich.panel import Panel
from rich.rule import Rule

from web_researcher.agent import build_agent
from web_researcher.config import get_settings
from web_researcher.report import save_report

app = typer.Typer(
    add_completion=False,
    help="Local web research agent (Ollama + SearXNG)",
)
console = Console()


def _format_tool_args(args: dict) -> str:
    parts = []
    for k, v in args.items():
        v_str = str(v)
        if len(v_str) > 120:
            v_str = v_str[:117] + "..."
        parts.append(f"{k}={v_str!r}")
    return ", ".join(parts)


def _short(text: str, n: int = 240) -> str:
    text = text.strip().replace("\n", " ")
    return text if len(text) <= n else text[: n - 1] + "…"


@app.command()
def main(
    question: str = typer.Argument(..., help="The research question"),
    model: Optional[str] = typer.Option(
        None, "--model", "-m", help="Override OLLAMA_MODEL"
    ),
    max_iterations: Optional[int] = typer.Option(
        None, "--max-iterations", help="Override MAX_ITERATIONS"
    ),
    output_dir: Path = typer.Option(
        Path("reports"), "--output-dir", "-o", help="Where to save the markdown report"
    ),
    no_save: bool = typer.Option(
        False, "--no-save", help="Skip writing the markdown report file"
    ),
):
    """Research QUESTION using SearXNG + Ollama, stream progress, save report."""
    settings = get_settings()
    if model:
        settings.ollama_model = model
    if max_iterations:
        settings.max_iterations = max_iterations

    console.print(
        Panel.fit(
            f"[bold]Question:[/bold] {question}\n"
            f"[dim]model:[/dim] {settings.ollama_model}  "
            f"[dim]summarizer:[/dim] {settings.ollama_summarizer_model}  "
            f"[dim]searxng:[/dim] {settings.searxng_url}",
            title="web-researcher",
            border_style="cyan",
        )
    )

    agent = build_agent(settings)
    inputs = {"messages": [HumanMessage(content=question)]}
    config = {"recursion_limit": settings.max_iterations * 2 + 5}

    final_text = ""
    step = 0
    try:
        for event in agent.stream(inputs, config=config, stream_mode="values"):
            messages = event.get("messages", [])
            if not messages:
                continue
            last = messages[-1]

            if isinstance(last, AIMessage):
                step += 1
                tool_calls = getattr(last, "tool_calls", None) or []
                if tool_calls:
                    for tc in tool_calls:
                        name = tc.get("name", "?")
                        args = tc.get("args", {}) or {}
                        console.print(
                            Rule(f"[bold cyan]Step {step}[/bold cyan]  →  "
                                 f"[yellow]{name}[/yellow]({_format_tool_args(args)})",
                                 style="cyan")
                        )
                    if last.content:
                        console.print(f"[dim]thought:[/dim] {_short(str(last.content))}")
                else:
                    # Final answer
                    final_text = str(last.content)

            elif isinstance(last, ToolMessage):
                name = getattr(last, "name", "tool")
                payload = str(last.content)
                # Try to render search results compactly
                preview = payload
                try:
                    obj = json.loads(payload)
                    if isinstance(obj, dict) and "results" in obj:
                        lines = []
                        for i, r in enumerate(obj["results"][:5], 1):
                            lines.append(f"  {i}. {r.get('title','')}  [dim]{r.get('url','')}[/dim]")
                        if obj.get("error"):
                            lines.append(f"  [red]error:[/red] {obj['error']}")
                        preview = "\n".join(lines) if lines else _short(payload)
                    elif isinstance(obj, dict) and "text" in obj:
                        title = obj.get("title", "")
                        preview = f"  [bold]{title}[/bold]\n  {_short(obj['text'], 300)}"
                        if obj.get("truncated"):
                            preview += "\n  [yellow](truncated)[/yellow]"
                    elif isinstance(obj, dict) and obj.get("error"):
                        preview = f"  [red]error:[/red] {obj['error']}"
                except (json.JSONDecodeError, TypeError):
                    preview = _short(payload, 300)
                console.print(f"[green]{name}[/green] →")
                console.print(preview)
    except Exception as e:
        console.print(f"[bold red]Agent error:[/bold red] {e}")
        raise typer.Exit(code=1)

    console.print(Rule("[bold green]Final report[/bold green]", style="green"))
    if final_text:
        console.print(Markdown(final_text))
    else:
        console.print("[red]No final answer produced.[/red]")
        raise typer.Exit(code=2)

    if not no_save and final_text:
        path = save_report(question, final_text, output_dir)
        console.print(f"\n[dim]Saved:[/dim] [bold]{path}[/bold]")


if __name__ == "__main__":
    app()
