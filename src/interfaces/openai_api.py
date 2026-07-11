"""OpenAI-compatible API server for Media Agent."""
import json
import time
import uuid

from fastapi import FastAPI, Header, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from src.config import get_settings

app = FastAPI(title="Media Agent", version="0.1.0")


class ChatMessage(BaseModel):
    role: str
    content: str


class ChatCompletionRequest(BaseModel):
    model: str = "media-agent"
    messages: list[ChatMessage]
    stream: bool = False
    temperature: float | None = None


def _check_auth(authorization: str | None):
    import hmac
    settings = get_settings()
    api_key = settings.server.get("api_key", "")
    if not api_key:
        return  # No key configured = no auth required
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(401, "Missing or invalid Authorization header")
    token = authorization.removeprefix("Bearer ")
    # Constant-time comparison to prevent timing attacks
    if not hmac.compare_digest(token, api_key):
        raise HTTPException(401, "Invalid API key")


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


async def _answer_stateless(messages: list[ChatMessage]) -> str:
    """Answer an OpenAI-style request (client resends full history each call).

    The last user message goes router-first (deterministic fast path); on a
    miss, the whole history is replayed into a throwaway agent thread, which
    is deleted afterwards so per-request threads don't leak in MemorySaver.
    """
    from src.graphs.conversational import forget_thread, run_agent
    from src.graphs.router import try_route

    last_user = next((m.content for m in reversed(messages) if m.role == "user"), "")
    thread_id = f"api-{uuid.uuid4().hex}"
    try:
        if last_user:
            routed = await try_route(last_user, thread_id)
            if routed is not None:
                return routed
        return await run_agent(
            "", thread_id,
            messages=[{"role": m.role, "content": m.content} for m in messages],
        )
    finally:
        forget_thread(thread_id)


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
    else:
        content = await _answer_stateless(request.messages)
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
    """Stream agent response as OpenAI-compatible SSE chunks."""
    from src.graphs.conversational import forget_thread, stream_agent
    from src.graphs.router import try_route

    chunk_id = f"chatcmpl-{uuid.uuid4().hex[:8]}"
    created = int(time.time())

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

    # Initial chunk
    yield make_chunk()

    last_user = next((m.content for m in reversed(messages) if m.role == "user"), "")
    thread_id = f"api-{uuid.uuid4().hex}"
    try:
        routed = await try_route(last_user, thread_id) if last_user else None
        if routed is not None:
            yield make_chunk(content=routed)
        else:
            async for text in stream_agent(
                "", thread_id,
                messages=[{"role": m.role, "content": m.content} for m in messages],
            ):
                yield make_chunk(content=text)
    except Exception as e:
        yield make_chunk(content=f"\n\n[Error: {e}]")
    finally:
        forget_thread(thread_id)

    # Final chunk
    yield make_chunk(finish_reason="stop")
    yield "data: [DONE]\n\n"
