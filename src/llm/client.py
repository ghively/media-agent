"""LLM client — local-first Ollama with optional hosted fallback.

The fallback is wired with LangChain's `.with_fallbacks()`, so any error
raised by the local model (connection refused, timeout, etc.) automatically
retries the same call against the hosted model.
"""
from langchain_core.language_models import BaseChatModel
from langchain_core.runnables import Runnable


class MediaLLM:
    """Local-first LLM router with optional hosted fallback."""

    def __init__(
        self,
        ollama_url: str,
        ollama_model: str,
        fallback_url: str = "",
        fallback_key: str = "",
        fallback_model: str = "",
        temperature: float = 0,
        timeout: int | None = None,
    ):
        from langchain_ollama import ChatOllama

        self.local_llm: BaseChatModel = ChatOllama(
            base_url=ollama_url,
            model=ollama_model,
            temperature=temperature,
        )
        self.fallback_llm: BaseChatModel | None = None
        if fallback_url and fallback_key and fallback_model:
            from langchain_openai import ChatOpenAI
            self.fallback_llm = ChatOpenAI(
                base_url=fallback_url,
                api_key=fallback_key,
                model=fallback_model,
                temperature=temperature,
                timeout=timeout,
            )

    def runnable(self, tools: list | None = None) -> Runnable:
        """Build the model runnable for the agent.

        Binds tools to both the local and fallback models so the fallback
        can also call tools, then chains them with `.with_fallbacks()`.
        """
        local = self.local_llm.bind_tools(tools) if tools else self.local_llm
        if self.fallback_llm is None:
            return local
        fallback = self.fallback_llm.bind_tools(tools) if tools else self.fallback_llm
        return local.with_fallbacks([fallback])


def create_llm() -> MediaLLM:
    """Create MediaLLM from settings."""
    from src.config import get_settings
    llm_cfg = get_settings().llm
    return MediaLLM(
        ollama_url=llm_cfg.get("ollama_url", "http://localhost:11434"),
        ollama_model=llm_cfg.get("ollama_model", "qwen3.5:9b"),
        fallback_url=llm_cfg.get("hosted_url", ""),
        fallback_key=llm_cfg.get("hosted_key", ""),
        fallback_model=llm_cfg.get("hosted_model", ""),
        temperature=llm_cfg.get("temperature", 0),
        timeout=llm_cfg.get("timeout"),
    )
