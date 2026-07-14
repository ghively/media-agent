"""OpenAI-compatible API server for Media Agent."""
import hashlib
import inspect
import json
import time
import uuid
from contextlib import asynccontextmanager

from fastapi import FastAPI, Header, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from src.config import get_settings

# Startup/shutdown hooks appended by main._run_server before uvicorn boots
# (modern FastAPI only supports lifecycle via the lifespan context).
startup_hooks: list = []
shutdown_hooks: list = []


async def _run_hooks(hooks: list) -> None:
    for hook in hooks:
        result = hook()
        if inspect.isawaitable(result):
            await result


@asynccontextmanager
async def _lifespan(app: FastAPI):
    await _run_hooks(startup_hooks)
    yield
    await _run_hooks(shutdown_hooks)


app = FastAPI(title="Media Agent", version="0.1.0", lifespan=_lifespan)


def _estimate_tokens(text: str) -> int:
    """Rough token estimate (~4 chars/token) so clients see non-zero usage."""
    return max(1, len(text) // 4) if text else 0


def _router_thread_id(messages: list) -> str:
    """Stable pseudo-thread for the stateless API's *router* state.

    OpenAI-style clients resend the full history each call and carry no
    thread id, so a per-request uuid would strand the router's pending
    confirmations: it asks "yes/no", and the "yes" arrives on a different
    thread. Keying on the conversation's first user message keeps the
    confirmation flow working across requests. (Two conversations opening
    with an identical first message would share this slot — acceptable for
    a personal deployment, and entries expire after 15 minutes.)
    """
    first_user = next((m.content for m in messages if m.role == "user"), "")
    digest = hashlib.sha256(first_user.encode("utf-8", "replace")).hexdigest()[:16]
    return f"api-{digest}"


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

    The last user message goes router-first (deterministic fast path) on a
    *stable* router thread so pending confirmations survive across requests.
    On a miss, the whole history is replayed into a throwaway agent thread,
    which is deleted afterwards so per-request threads don't leak.
    """
    from src.graphs.conversational import forget_thread, run_agent
    from src.graphs.router import try_route

    last_user = next((m.content for m in reversed(messages) if m.role == "user"), "")
    agent_thread = f"api-{uuid.uuid4().hex}"
    try:
        if last_user:
            routed = await try_route(last_user, _router_thread_id(messages))
            if routed is not None:
                return routed
        return await run_agent(
            "", agent_thread,
            messages=[{"role": m.role, "content": m.content} for m in messages],
        )
    finally:
        await forget_thread(agent_thread)


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
        # Estimated usage (~4 chars/token): the agent runs local models and
        # doesn't meter exactly, but zeros confuse client-side accounting.
        prompt_tokens = sum(_estimate_tokens(m.content) for m in request.messages)
        completion_tokens = _estimate_tokens(content)
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
            "usage": {
                "prompt_tokens": prompt_tokens,
                "completion_tokens": completion_tokens,
                "total_tokens": prompt_tokens + completion_tokens,
            },
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
    agent_thread = f"api-{uuid.uuid4().hex}"
    try:
        routed = await try_route(last_user, _router_thread_id(messages)) if last_user else None
        if routed is not None:
            yield make_chunk(content=routed)
        else:
            async for text in stream_agent(
                "", agent_thread,
                messages=[{"role": m.role, "content": m.content} for m in messages],
            ):
                yield make_chunk(content=text)
    except Exception:
        # Never leak internal exception detail to API clients.
        yield make_chunk(content="\n\n[Error: the agent failed to answer — check the server logs.]")
    finally:
        await forget_thread(agent_thread)

    # Final chunk
    yield make_chunk(finish_reason="stop")
    yield "data: [DONE]\n\n"
