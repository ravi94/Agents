"""Runtime configuration loaded from environment / .env."""

from typing import Optional

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # Ollama
    ollama_host: str = "http://localhost:11434"
    ollama_model: str = "qwen2.5:14b"
    ollama_summarizer_model: str = "llama3.1:8b"

    # SearXNG — required; no default so misconfiguration fails loud
    searxng_url: str = Field(..., description="Base URL of your SearXNG instance")

    # Agent behavior
    max_iterations: int = 12
    max_results_per_search: int = 8
    request_timeout_seconds: int = 20
    max_page_chars: int = 12_000

    # Observability (Phoenix / OpenInference)
    # Opt-in: keep default off so the standard run has no Phoenix overhead and
    # missing observability deps don't break anything until explicitly turned on.
    tracing_enabled: bool = False
    phoenix_host: str = "127.0.0.1"
    phoenix_port: int = 6006
    # Project name shown in the Phoenix UI; one run = one trace tree
    phoenix_project_name: str = "web-researcher"
    # When set, point traces at an already-running Phoenix server instead of
    # launching an embedded one. Embedded mode uses an in-memory DB that dies
    # with the CLI process; a standalone `phoenix serve` persists traces and
    # keeps the UI up after the run finishes. Base URL, e.g. http://localhost:6006
    phoenix_collector_endpoint: Optional[str] = None


def get_settings() -> Settings:
    return Settings()  # type: ignore[call-arg]
