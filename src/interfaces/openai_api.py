"""OpenAI-compatible API server for Media Agent."""
import json
import time
import uuid

from fastapi import FastAPI, Header, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from src.config import get_settings

app = FastAPI(title="Media Agent", version="0.1.0")

# How many agent↔tool round-trips to allow per request.
RECURSION_LIMIT = 25

# Build agent on startup (not module-level to avoid import errors in tests)
_agent = None


def _get_agent():
    global _agent
    if _agent is None:
        from src.graphs.conversational import create_agent
        _agent = create_agent()
    return _agent


class ChatMessage(BaseModel):
    role: str
    content: str


class ChatCompletionRequest(BaseModel):
    model: str = "media-agent"
    messages: list[ChatMessage]
    stream: bool = False
    temperature: float | None = None


def _check_auth(authorization: str | None):
    settings = get_settings()
    api_key = settings.server.get("api_key", "")
    if not api_key:
        return  # No key configured = no auth required
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(401, "Missing or invalid Authorization header")
    token = authorization.removeprefix("Bearer ")
    if token != api_key:
        raise HTTPException(401, "Invalid API key")


def _graph_input(messages: list[ChatMessage]) -> dict:
    """Convert OpenAI-style messages into LangGraph input.

    The agent graph injects its own system prompt; client-supplied system
    messages are dropped so front-ends (Open WebUI etc.) can't accidentally
    override the agent's tool-use instructions. Full user/assistant history
    is passed through, which is how the API stays stateless but
    conversation-aware.
    """
    return {
        "messages": [
            {"role": m.role, "content": m.content}
            for m in messages
            if m.role in ("user", "assistant")
        ]
    }


async def _run_agent(messages: list[ChatMessage]) -> str:
    """Run the agent to completion and return clean, user-safe text."""
    from langgraph.errors import GraphRecursionError
    from src.llm.postprocess import clean_response

    agent = _get_agent()
    try:
        result = await agent.ainvoke(
            _graph_input(messages),
            config={"recursion_limit": RECURSION_LIMIT},
        )
    except GraphRecursionError:
        return (
            "⚠️ I hit my step limit before finishing — the model appears to be "
            "looping on tool calls. Try a more specific request, or configure "
            "a stronger model."
        )
    return clean_response(result["messages"][-1])


@app.get("/health")
async def health():
    return {"status": "ok"}


@app.get("/v1/models")
async def list_models(authorization: str | None = Header(None)):
    _check_auth(authorization)
    return {
        "object": "list",
        "data": [
            {"id": "media-agent", "object": "model", "owned_by": "media-agent"}
        ],
    }


@app.post("/v1/chat/completions")
async def chat_completions(
    request: ChatCompletionRequest,
    authorization: str | None = Header(None),
):
    _check_auth(authorization)

    if request.stream:
        return StreamingResponse(
            _stream_response(request.messages),
            media_type="text/event-stream",
        )

    content = await _run_agent(request.messages)
    return {
        "id": f"chatcmpl-{uuid.uuid4().hex[:8]}",
        "object": "chat.completion",
        "created": int(time.time()),
        "model": "media-agent",
        "choices": [
            {
                "index": 0,
                "message": {"role": "assistant", "content": content},
                "finish_reason": "stop",
            }
        ],
        "usage": {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0},
    }


async def _stream_response(messages: list[ChatMessage]):
    """Stream the agent's answer as OpenAI-compatible SSE chunks.

    Two modes (``server.token_streaming``, default true):

    - **Token mode**: real typing effect via ``stream_mode="messages"``.
      Tool-call chunks are skipped (they carry ``tool_call_chunks``, not
      text) and a stateful ``ThinkStreamFilter`` suppresses ``<think>``
      blocks even when tags split across chunks — so neither tool calls nor
      reasoning traces reach the client mid-stream.
    - **Message mode** (``token_streaming: false``): each completed,
      tool-call-free agent message is cleaned and emitted whole — the most
      conservative option.
    """
    from langgraph.errors import GraphRecursionError
    from src.llm.postprocess import clean_response, ThinkStreamFilter, message_text

    chunk_id = f"chatcmpl-{uuid.uuid4().hex[:8]}"
    created = int(time.time())
    agent = _get_agent()
    token_mode = bool(get_settings().server.get("token_streaming", True))

    def make_chunk(content: str = "", finish_reason: str | None = None) -> str:
        payload = {
            "id": chunk_id,
            "object": "chat.completion.chunk",
            "created": created,
            "model": "media-agent",
            "choices": [
                {
                    "index": 0,
                    "delta": {"content": content} if content else {},
                    "finish_reason": finish_reason,
                }
            ],
        }
        return f"data: {json.dumps(payload)}\n\n"

    # Initial chunk announces the assistant role
    yield make_chunk()

    emitted = False
    try:
        if token_mode:
            think_filter = ThinkStreamFilter()
            last_text_by_msg: dict = {}
            async for item in agent.astream(
                _graph_input(messages),
                config={"recursion_limit": RECURSION_LIMIT},
                stream_mode="messages",
            ):
                chunk_msg, metadata = item
                if metadata.get("langgraph_node") not in ("model", "agent"):
                    continue  # tool-node output is model input, not chat output
                if getattr(chunk_msg, "tool_call_chunks", None) or \
                        getattr(chunk_msg, "tool_calls", None):
                    continue  # part of a tool call, not an answer
                text = message_text(chunk_msg)
                if not text:
                    continue
                # guard against the known cumulative-duplicate chunk quirk:
                # skip a chunk that just repeats everything already seen
                key = getattr(chunk_msg, "id", None)
                seen = last_text_by_msg.get(key, "")
                if seen and text == seen:
                    continue
                last_text_by_msg[key] = seen + text
                safe = think_filter.feed(text)
                if safe:
                    yield make_chunk(content=safe)
                    emitted = True
            tail = think_filter.flush()
            if tail:
                yield make_chunk(content=tail)
                emitted = True
        else:
            async for update in agent.astream(
                _graph_input(messages),
                config={"recursion_limit": RECURSION_LIMIT},
                stream_mode="updates",
            ):
                for node, payload in update.items():
                    if node not in ("model", "agent"):
                        continue
                    for message in (payload or {}).get("messages", []):
                        if getattr(message, "tool_calls", None):
                            continue  # intermediate tool-calling turn
                        text = clean_response(message)
                        if text:
                            yield make_chunk(content=text)
                            emitted = True
    except GraphRecursionError:
        yield make_chunk(
            content="⚠️ I hit my step limit before finishing — the model appears "
                    "to be looping on tool calls. Try a more specific request."
        )
        emitted = True
    except Exception as e:
        yield make_chunk(content=f"\n\n[Error: {type(e).__name__}: {e}]")
        emitted = True

    if not emitted:
        yield make_chunk(content="⚠️ The agent finished without producing a reply.")

    yield make_chunk(finish_reason="stop")
    yield "data: [DONE]\n\n"
