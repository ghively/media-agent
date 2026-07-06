"""OpenAI-compatible API server for Media Agent."""
import json
import time
import uuid

from fastapi import FastAPI, Header, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from src.config import get_settings

app = FastAPI(title="Media Agent", version="0.1.0")

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
        agent = _get_agent()
        result = await agent.ainvoke({
            "messages": [{"role": m.role, "content": m.content} for m in request.messages]
        })
        content = result["messages"][-1].content
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
    chunk_id = f"chatcmpl-{uuid.uuid4().hex[:8]}"
    created = int(time.time())
    agent = _get_agent()

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

    # Stream tokens from agent
    try:
        async for event in agent.astream_events(
            {"messages": [{"role": m.role, "content": m.content} for m in messages]},
            version="v2",
        ):
            if event["event"] == "on_chat_model_stream":
                chunk = event["data"].get("chunk")
                if chunk and hasattr(chunk, "content") and chunk.content:
                    yield make_chunk(content=chunk.content)
    except Exception as e:
        yield make_chunk(content=f"\n\n[Error: {e}]")

    # Final chunk
    yield make_chunk(finish_reason="stop")
    yield "data: [DONE]\n\n"
