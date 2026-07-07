"""OpenAI-compatible API server for Media Agent."""
import json
import time
import uuid

from fastapi import FastAPI, Header, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from src.config import get_settings

app = FastAPI(title="Media Agent", version="0.1.0")


def _parse_domain(model: str) -> str | None:
    """Allow clients to force a domain with model='media-agent:<domain>'
    (e.g. 'media-agent:tv'). Plain 'media-agent' routes automatically."""
    if ":" in model:
        return model.split(":", 1)[1] or None
    return None


def _resolve(messages: list["ChatMessage"], model: str):
    """Route to the domain agent for this conversation."""
    from src.graphs.conversational import resolve_agent
    dict_messages = [{"role": m.role, "content": m.content} for m in messages]
    agent, domain = resolve_agent(dict_messages, _parse_domain(model))
    return agent, dict_messages, domain


def _recursion_limit() -> int:
    from src.graphs.conversational import _recursion_limit as limit
    return limit()


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


@app.get("/health")
async def health():
    return {"status": "ok"}


@app.get("/v1/models")
async def list_models(authorization: str | None = Header(None)):
    _check_auth(authorization)
    from src.graphs.conversational import DOMAIN_TOOLS
    models = ["media-agent"] + [f"media-agent:{d}" for d in DOMAIN_TOOLS if d != "core"]
    return {
        "object": "list",
        "data": [
            {"id": m, "object": "model", "owned_by": "media-agent"} for m in models
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
            _stream_response(request.messages, request.model),
            media_type="text/event-stream",
        )
    else:
        agent, messages, _ = _resolve(request.messages, request.model)
        result = await agent.ainvoke(
            {"messages": messages},
            config={"recursion_limit": _recursion_limit()},
        )
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


async def _stream_response(messages: list[ChatMessage], model: str = "media-agent"):
    """Stream agent response as OpenAI-compatible SSE chunks."""
    chunk_id = f"chatcmpl-{uuid.uuid4().hex[:8]}"
    created = int(time.time())
    agent, dict_messages, _ = _resolve(messages, model)

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
            {"messages": dict_messages},
            version="v2",
            config={"recursion_limit": _recursion_limit()},
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
