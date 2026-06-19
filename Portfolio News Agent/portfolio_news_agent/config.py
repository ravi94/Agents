"""Configuration: load settings from env/.env and holdings from holdings.yaml."""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

import yaml
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent


@dataclass
class Holding:
    ticker: str
    name: str = ""
    notes: str = ""


@dataclass
class Config:
    # LLM
    ollama_base_url: str
    model_name: str
    tool_mode: str  # native | prompt | auto
    # Search
    search_provider: str
    serpapi_api_key: str
    # Search throttling + cache (mitigates DuckDuckGo anti-bot throttling)
    search_min_interval: float
    search_jitter: float
    search_cache_enabled: bool
    search_cache_dir: Path
    # Guardrails
    max_iterations: int
    max_tool_calls: int
    run_timeout_seconds: int
    fetch_char_budget: int
    # Delivery
    delivery_mode: str  # email | file
    output_dir: Path
    # Email
    smtp_host: str
    smtp_port: int
    smtp_username: str
    smtp_password: str
    email_from: str
    email_to: str
    # Data
    holdings: list[Holding] = field(default_factory=list)

    def validate_for_email(self) -> None:
        """Raise if required email fields are missing (skipped in dry-run)."""
        missing = [
            k
            for k in ("smtp_host", "smtp_username", "smtp_password", "email_from", "email_to")
            if not getattr(self, k)
        ]
        if missing:
            raise ValueError(f"Missing email config: {', '.join(missing)}")


def _load_holdings(path: Path) -> list[Holding]:
    if not path.exists():
        raise FileNotFoundError(f"holdings file not found: {path}")
    data = yaml.safe_load(path.read_text()) or {}
    raw = data.get("holdings") or []
    if not raw:
        raise ValueError("holdings.yaml has no holdings")
    holdings: list[Holding] = []
    for i, item in enumerate(raw):
        if not isinstance(item, dict) or not item.get("ticker"):
            raise ValueError(f"holdings[{i}] missing required 'ticker'")
        holdings.append(
            Holding(
                ticker=str(item["ticker"]).strip().upper(),
                name=str(item.get("name", "")).strip(),
                notes=str(item.get("notes", "")).strip(),
            )
        )
    return holdings


def load_config(holdings_path: Path | None = None) -> Config:
    load_dotenv(ROOT / ".env")
    holdings_path = holdings_path or ROOT / "holdings.yaml"

    provider = os.getenv("SEARCH_PROVIDER", "duckduckgo").strip().lower()
    if provider not in ("duckduckgo", "serpapi"):
        raise ValueError(f"unknown SEARCH_PROVIDER: {provider!r}")

    tool_mode = os.getenv("TOOL_MODE", "auto").strip().lower()
    if tool_mode not in ("native", "prompt", "auto"):
        raise ValueError(f"unknown TOOL_MODE: {tool_mode!r}")

    delivery_mode = os.getenv("DELIVERY_MODE", "email").strip().lower()
    if delivery_mode not in ("email", "file"):
        raise ValueError(f"unknown DELIVERY_MODE: {delivery_mode!r}")

    return Config(
        ollama_base_url=os.getenv("OLLAMA_BASE_URL", "http://localhost:11434/v1").rstrip("/"),
        model_name=os.getenv("MODEL_NAME", "qwen3:27b"),
        tool_mode=tool_mode,
        search_provider=provider,
        serpapi_api_key=os.getenv("SERPAPI_API_KEY", ""),
        search_min_interval=float(os.getenv("SEARCH_MIN_INTERVAL_SECONDS", "2.0")),
        search_jitter=float(os.getenv("SEARCH_JITTER_SECONDS", "1.0")),
        search_cache_enabled=os.getenv("SEARCH_CACHE", "true").strip().lower()
        not in ("0", "false", "no", "off", ""),
        search_cache_dir=Path(
            os.getenv("SEARCH_CACHE_DIR", "").strip() or str(ROOT / ".search_cache")
        ).expanduser(),
        max_iterations=int(os.getenv("MAX_ITERATIONS", "8")),
        max_tool_calls=int(os.getenv("MAX_TOOL_CALLS", "20")),
        run_timeout_seconds=int(os.getenv("RUN_TIMEOUT_SECONDS", "300")),
        fetch_char_budget=int(os.getenv("FETCH_CHAR_BUDGET", "8000")),
        delivery_mode=delivery_mode,
        output_dir=Path(os.getenv("OUTPUT_DIR", "").strip() or str(ROOT)).expanduser(),
        smtp_host=os.getenv("SMTP_HOST", ""),
        smtp_port=int(os.getenv("SMTP_PORT", "587")),
        smtp_username=os.getenv("SMTP_USERNAME", ""),
        smtp_password=os.getenv("SMTP_PASSWORD", ""),
        email_from=os.getenv("EMAIL_FROM", ""),
        email_to=os.getenv("EMAIL_TO", ""),
        holdings=_load_holdings(holdings_path),
    )
