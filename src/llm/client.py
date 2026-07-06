"""LLM client — Ollama is the primary model; hosted endpoint is optional backup.

Every request goes to Ollama. If a hosted endpoint is configured, the agent
graph attaches LangChain's ``ModelFallbackMiddleware`` so a FAILED Ollama
call (server down, model crashed) retries against it — nothing else ever
routes there. Leave the hosted settings empty for a pure-Ollama deployment.

Ollama specifics that matter for a tool-calling agent:

- ``num_ctx``: Ollama's default context window (often 2048–4096 tokens) is
  smaller than the system prompt + ~40 tool schemas this agent binds. When
  the context overflows, Ollama silently truncates the prompt — the model
  loses its tool definitions and starts hallucinating or printing tool-call
  JSON as text. We default to 16384 and make it configurable.
- ``reasoning``: for thinking models (qwen3 / qwen3.5, deepseek-r1) this
  asks Ollama to separate or disable the reasoning trace. It is optional
  because not every model accepts the flag, and it is unreliable for some
  Qwen builds — user-facing output is additionally cleaned in
  ``src.llm.postprocess``.
"""
from langchain_core.language_models import BaseChatModel


class MediaLLM:
    """Builds the local Ollama model and optional hosted fallback."""

    def __init__(
        self,
        ollama_url: str,
        ollama_model: str,
        temperature: float = 0.0,
        num_ctx: int = 16384,
        keep_alive: str | int | None = "10m",
        reasoning: bool | None = None,
        fallback_url: str = "",
        fallback_key: str = "",
        fallback_model: str = "",
    ):
        from langchain_ollama import ChatOllama

        ollama_kwargs = {
            "base_url": ollama_url,
            "model": ollama_model,
            "temperature": temperature,
            "num_ctx": num_ctx,
        }
        if keep_alive is not None:
            ollama_kwargs["keep_alive"] = keep_alive
        if reasoning is not None:
            ollama_kwargs["reasoning"] = reasoning

        self.local_llm: BaseChatModel = ChatOllama(**ollama_kwargs)

        self.fallback_llm: BaseChatModel | None = None
        if fallback_url and fallback_key and fallback_model:
            from langchain_openai import ChatOpenAI

            self.fallback_llm = ChatOpenAI(
                base_url=fallback_url,
                api_key=fallback_key,
                model=fallback_model,
                temperature=temperature,
            )



def _coerce_reasoning(value) -> bool | None:
    """Normalize the reasoning setting to True/False/None.

    Values may arrive as strings when set via ${ENV_VAR} substitution
    (e.g. OLLAMA_REASONING=false). None/empty means "don't send the think
    flag at all" — required for non-thinking models (qwen2.5, llama3.x),
    which reject it.
    """
    if value is None or isinstance(value, bool):
        return value
    text = str(value).strip().lower()
    if text in ("", "null", "none", "~"):
        return None
    return text in ("1", "true", "yes", "on")


def create_llm() -> MediaLLM:
    """Create MediaLLM from settings."""
    from src.config import get_settings

    llm_cfg = get_settings().llm
    return MediaLLM(
        ollama_url=llm_cfg.get("ollama_url", "http://localhost:11434"),
        ollama_model=llm_cfg.get("ollama_model", "qwen2.5:7b"),
        temperature=float(llm_cfg.get("temperature", 0) or 0),
        num_ctx=int(llm_cfg.get("num_ctx", 16384)),
        keep_alive=llm_cfg.get("keep_alive", "10m"),
        reasoning=_coerce_reasoning(llm_cfg.get("reasoning", None)),
        fallback_url=llm_cfg.get("hosted_url", ""),
        fallback_key=llm_cfg.get("hosted_key", ""),
        fallback_model=llm_cfg.get("hosted_model", ""),
    )
