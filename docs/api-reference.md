# Media Agent — API Reference

**Base URL:** `http://your-gpu-host:8088`  
**Auth:** Bearer token (`MEDIA_AGENT_API_KEY` from `.env`)  
**Protocol:** OpenAI-compatible (works with any OpenAI-compatible client)

---

## Endpoints

### Health Check

```
GET /health
```

**Auth:** None (public endpoint, used by Docker HEALTHCHECK)

**Response:**
```json
{"status": "ok"}
```

---

### List Models

```
GET /v1/models
```

**Auth:** Bearer token required (if `api_key` is configured)

**Response:**
```json
{
  "object": "list",
  "data": [
    {
      "id": "media-agent",
      "object": "model",
      "owned_by": "media-agent"
    }
  ]
}
```

---

### Chat Completions

```
POST /v1/chat/completions
```

**Auth:** Bearer token required

**Request Body:**

| Field | Type | Required | Description |
|---|---|---|---|
| `model` | string | No (default: `"media-agent"`) | Must be `"media-agent"` |
| `messages` | array | Yes | Chat messages in OpenAI format |
| `stream` | boolean | No (default: `false`) | Enable SSE streaming |
| `temperature` | float | No (default: `0`) | Ignored — agent uses temperature=0 |

**Message Format:**
```json
{
  "role": "user",
  "content": "What TV shows do I have?"
}
```

#### Non-Streaming Response

```json
{
  "id": "chatcmpl-a1b2c3d4",
  "object": "chat.completion",
  "created": 1751700000,
  "model": "media-agent",
  "choices": [
    {
      "index": 0,
      "message": {
        "role": "assistant",
        "content": "You're monitoring 47 shows..."
      },
      "finish_reason": "stop"
    }
  ],
  "usage": {
    "prompt_tokens": 0,
    "completion_tokens": 0,
    "total_tokens": 0
  }
}
```

#### Streaming Response (SSE)

When `stream: true`, the response is a `text/event-stream`:

```
data: {"id":"chatcmpl-a1b2c3d4","object":"chat.completion.chunk","created":1751700000,"model":"media-agent","choices":[{"index":0,"delta":{},"finish_reason":null}]}

data: {"id":"chatcmpl-a1b2c3d4","object":"chat.completion.chunk","created":1751700000,"model":"media-agent","choices":[{"index":0,"delta":{"content":"You"},"finish_reason":null}]}

data: {"id":"chatcmpl-a1b2c3d4","object":"chat.completion.chunk","created":1751700000,"model":"media-agent","choices":[{"index":0,"delta":{"content":"'re monitoring"},"finish_reason":null}]}

data: {"id":"chatcmpl-a1b2c3d4","object":"chat.completion.chunk","created":1751700000,"model":"media-agent","choices":[{"index":0,"delta":{},"finish_reason":"stop"}]}

data: [DONE]
```

Each chunk follows the standard OpenAI SSE format:
- Prefixed with `data: `
- Suffixed with `\n\n`
- Final chunk has `"finish_reason": "stop"`
- Terminator is `data: [DONE]\n\n`

---

### Dashboard

```
GET /dashboard
```

**Auth:** None (serves the HTML shell only)

Returns a self-contained HTML page (no external dependencies) showing:
- Service health cards (Sonarr, Radarr, Emby, SABnzbd)
- Active downloads
- Recent activity

```
GET /api/dashboard/data
```

**Auth:** Bearer token required (if `api_key` is configured)

Returns JSON health/activity data for programmatic access.

```
POST /api/dashboard/chat
```

**Auth:** Bearer token required (if `api_key` is configured)

Streams the agent's response (SSE) for a dashboard chat message. Body:
`{"message": "..."}`. This route drives the full agent, so it is gated behind
the same `MEDIA_AGENT_API_KEY` as the `/v1` endpoints — set a key (and reach the
service over loopback or an authenticated proxy) before exposing it.

---

## Example Requests

### cURL — Non-Streaming

```bash
curl -X POST http://localhost:8088/v1/chat/completions \
  -H "Authorization: Bearer YOUR_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{
    "model": "media-agent",
    "messages": [
      {"role": "user", "content": "list my tv shows"}
    ]
  }'
```

### cURL — Streaming

```bash
curl -X POST http://localhost:8088/v1/chat/completions \
  -H "Authorization: Bearer YOUR_API_KEY" \
  -H "Content-Type: application/json" \
  -N \
  -d '{
    "model": "media-agent",
    "stream": true,
    "messages": [
      {"role": "user", "content": "what is downloading?"}
    ]
  }'
```

### Python (OpenAI SDK)

```python
from openai import OpenAI

client = OpenAI(
    base_url="http://your-gpu-host:8088/v1",
    api_key="YOUR_API_KEY",
)

response = client.chat.completions.create(
    model="media-agent",
    messages=[{"role": "user", "content": "add Breaking Bad"}],
)
print(response.choices[0].message.content)
```

### Python — Streaming

```python
stream = client.chat.completions.create(
    model="media-agent",
    stream=True,
    messages=[{"role": "user", "content": "what's downloading?"}],
)
for chunk in stream:
    if chunk.choices[0].delta.content:
        print(chunk.choices[0].delta.content, end="", flush=True)
```

---

## Connecting External Clients

### Open WebUI

1. Settings → Connections → Add connection
2. **URL:** `http://your-gpu-host:8088/v1`
3. **API Key:** your `MEDIA_AGENT_API_KEY`
4. The "media-agent" model appears in the dropdown

### Any OpenAI-Compatible Client

Point any client that supports custom OpenAI base URLs at `http://your-gpu-host:8088/v1` with your API key.

---

## Behavioral Notes

### Tool Calls Are Invisible

The agent calls tools internally (searching, adding, querying health) but the API response only contains the final natural-language answer. Tool calls and results are NOT exposed in the API response — they're internal to the LangGraph ReAct loop.

### Model Is Not a Real LLM

The `"model": "media-agent"` in the request is required for OpenAI compatibility but is ignored. The actual model is Qwen 3.5 9B via Ollama, configured in `settings.yaml`.

### Temperature Is Ignored

The agent uses `temperature=0` for deterministic behavior. The `temperature` field in the request is accepted but not passed through.

### First Request Latency

The first request after container start (or after Ollama model unload) takes 10-15 seconds as the model loads into VRAM. Subsequent requests are ~35 tok/s.

### Usage Stats Are Zero

The `usage` field in the response always returns zeros. Token counting is not implemented because the local Ollama model doesn't bill per-token.

---

## Rate Limiting

None. The agent processes one request at a time (single-threaded async). Concurrent requests queue internally. For production multi-user use, consider a reverse proxy with rate limiting.

---

## Error Responses

| HTTP Status | Cause |
|---|---|
| 401 | Missing or invalid API key |
| 422 | Malformed request body |
| 500 | Internal error (agent exception) |

Error response format follows standard FastAPI error structure:

```json
{
  "detail": "Invalid API key"
}
```

---

*Last updated: 2026-07-11*
