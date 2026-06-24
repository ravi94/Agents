"""Runtime configuration loaded from environment / .env."""

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


def get_settings() -> Settings:
    return Settings()  # type: ignore[call-arg]
