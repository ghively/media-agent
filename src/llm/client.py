"""LLM client with circuit breaker pattern for local-first routing."""
import asyncio
import time
from enum import Enum
from typing import Optional

from langchain_core.language_models import BaseChatModel


class CircuitState(Enum):
    CLOSED = "closed"
    OPEN = "open"
    HALF_OPEN = "half_open"


class MediaLLM:
    """Local-first LLM router with circuit breaker."""

    def __init__(
        self,
        ollama_url: str,
        ollama_model: str,
        fallback_url: str = "",
        fallback_key: str = "",
        fallback_model: str = "",
        temperature: float = 0.2,
        num_ctx: int = 8192,
        num_predict: int = 1024,
        keep_alive: str = "30m",
        reasoning: bool = False,
    ):
        from langchain_ollama import ChatOllama

        # keep_alive keeps the model resident in VRAM between requests —
        # without it Ollama may unload after 5m and every chat pays a
        # multi-second reload. num_predict caps runaway generations.
        # reasoning=False disables qwen3-style thinking blocks (major
        # latency win for tool-calling turns); dropped if the installed
        # langchain-ollama predates the parameter.
        ollama_kwargs = dict(
            base_url=ollama_url,
            model=ollama_model,
            temperature=temperature,
            num_ctx=num_ctx,
            num_predict=num_predict,
            keep_alive=keep_alive,
        )
        try:
            self.local_llm = ChatOllama(**ollama_kwargs, reasoning=reasoning)
        except Exception:
            self.local_llm = ChatOllama(**ollama_kwargs)
        self.fallback_llm = None
        if fallback_url and fallback_key:
            from langchain_openai import ChatOpenAI
            self.fallback_llm = ChatOpenAI(
                base_url=fallback_url,
                api_key=fallback_key,
                model=fallback_model,
                temperature=temperature,
            )

        self._state = CircuitState.CLOSED
        self._failures = 0
        self._last_failure_time = 0.0
        self._lock = asyncio.Lock()
        self._failure_threshold = 3
        self._recovery_timeout = 60
        self._half_open_calls = 0
        self._half_open_max = 1

    async def get_llm(self) -> BaseChatModel:
        async with self._lock:
            if self._state == CircuitState.CLOSED:
                return self.local_llm
            elif self._state == CircuitState.OPEN:
                if time.time() - self._last_failure_time > self._recovery_timeout:
                    self._state = CircuitState.HALF_OPEN
                    self._half_open_calls = 0
                    return self.local_llm
                return self.fallback_llm if self.fallback_llm else self.local_llm
            else:  # HALF_OPEN
                if self._half_open_calls < self._half_open_max:
                    self._half_open_calls += 1
                    return self.local_llm
                return self.fallback_llm if self.fallback_llm else self.local_llm

    async def record_success(self):
        async with self._lock:
            self._failures = 0
            self._state = CircuitState.CLOSED

    async def record_failure(self):
        async with self._lock:
            self._failures += 1
            self._last_failure_time = time.time()
            if self._failures >= self._failure_threshold:
                self._state = CircuitState.OPEN


def create_llm() -> MediaLLM:
    """Create MediaLLM from settings.

    Temperature defaults low (0.2): a 9B model picking among ~66 tools needs
    determinism far more than prose flair. Override via ``llm.temperature``.
    """
    from src.config import get_settings
    llm_cfg = get_settings().llm
    return MediaLLM(
        ollama_url=llm_cfg.get("ollama_url", "http://agent-lab-ollama-1:11435"),
        ollama_model=llm_cfg.get("ollama_model", "qwen3.5:9b"),
        fallback_url=llm_cfg.get("hosted_url", ""),
        fallback_key=llm_cfg.get("hosted_key", ""),
        fallback_model=llm_cfg.get("hosted_model", ""),
        temperature=llm_cfg.get("temperature", 0.2),
        num_ctx=llm_cfg.get("num_ctx", 8192),
        num_predict=llm_cfg.get("num_predict", 1024),
        keep_alive=llm_cfg.get("keep_alive", "30m"),
        reasoning=llm_cfg.get("reasoning", False),
    )
