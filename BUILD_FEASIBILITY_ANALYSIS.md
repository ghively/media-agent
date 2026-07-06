# Media Agent — Build Feasibility Analysis (Historical)

> **⚠️ HISTORICAL DOCUMENT** — This was the pre-build gap analysis. All gaps identified here were resolved during implementation. Preserved for decision history.

**Date:** 2026-07-05  
**Reviewer:** Hermes Agent  
**Status:** GAP ANALYSIS FOR CODEX MVP IMPLEMENTATION

---

## Executive Summary

**Overall Verdict: GAP - Needs Clarification Before Implementation**

While the spec provides excellent high-level architecture and vision, there are critical implementation gaps that would prevent Codex from building the MVP without making architectural decisions that may not match the author's intent.

**Blockers found:**
- 3 CRITICAL gaps (must resolve before starting)
- 8 MODERATE gaps (Codex will make default choices)
- 11 MINOR gaps (acceptable defaults exist)

**Recommendation:** Address critical gaps before delegating to Codex. Moderate gaps can be documented as "implementation details left to Codex" with expectations set.

---

## Detailed Analysis by Area

---

### 1. API Client Completeness

**Verdict: GAP - Moderate**

The spec lists 20 API tools across Sonarr, Radarr, and Emby but provides no implementation details about:
- Actual API endpoint URLs
- Authentication method
- Request/response formats
- Error handling requirements

#### Sonarr (8 tools specified)

**Spec says:**
```
search_tv(query) → returns matches with tvdbId
add_tv_show(tvdb_id, quality_profile_id=1, monitored=true)
list_tv_shows()
get_tv_queue()
get_tv_history()
search_missing_episodes()
get_tv_calendar(days=7)
get_tv_health()
```

**Missing details:**
- **Endpoint URLs:** Spec doesn't show actual endpoints like `/api/v3/series` or `/api/v3/queue`
- **Authentication:** Spec doesn't state Servarr uses `X-Api-Key` header
- **Response structures:** What does `search_tv` return? List of objects with `tvdbId`, `title`, `year`, `overview`, `images`?
- **Quality profile IDs:** Spec assumes `quality_profile_id=1` is valid - how to discover available profiles?
- **Error handling:** What to do when Sonarr returns 401/403/404/500?
- **Pagination:** Does `list_tv_shows` need pagination handling?

#### Radarr (7 tools specified)

**Missing details:** Same gaps as Sonarr
- Endpoint URLs not specified
- TMDb ID format validation not specified
- Response format for search results unclear

#### Emby (5 tools specified)

**Spec says:**
```
emby_search(query)
emby_recent(limit=20)
emby_libraries()
emby_scan(library_name=None)
emby_get_item(item_id)
```

**Missing details:**
- **Endpoint URLs:** Not specified (e.g., `/emby/Users/{userId}/Items`, `/emby/Library/Refresh`)
- **Authentication:** Emby uses either API key or user token - which should the agent use?
- **User ID requirement:** Many Emby endpoints require a user ID - how to get the admin user ID?
- **Response format:** What does a library item look like?
- **Discovery:** How to list all available libraries for the `emby_libraries()` tool?

**CRITICAL GAP #1:**
**What Codex needs:** The spec should include at least one example API client implementation showing:
- HTTP client setup (httpx vs requests)
- Authentication header injection
- One complete endpoint implementation with request/response models
- Error handling pattern

**Current state:** Codex would need to reverse-engineer the Servarr API from scratch or make assumptions that may be wrong.

**Recommendation:**
Add a "Tool Implementation Examples" section with:
```python
# Example: Sonarr search tool implementation
class SonarrClient:
    def __init__(self, url: str, api_key: str):
        self.base_url = url.rstrip("/")
        self.headers = {"X-Api-Key": api_key}

    async def search_tv(self, query: str) -> list[TVSeries]:
        """Search for TV series by name."""
        params = {"term": query}
        async with httpx.AsyncClient() as client:
            resp = await client.get(
                f"{self.base_url}/api/v3/series/lookup",
                headers=self.headers,
                params=params
            )
            resp.raise_for_status()
            return [TVSeries(**item) for item in resp.json()]
```

---

### 2. LangGraph Conversational Graph

**Verdict: GAP - Moderate**

The spec shows a flow diagram but lacks implementation details for LangGraph 1.x.

**What the spec provides:**
```
START → parse_intent → [route]
  ├── "status" query → call tools (health/queue/calendar) → format_response → END
  ├── "search" query → call search tools → format_response → END
  ├── "add" request → confirm with user → call add tool → format_response → END
  ├── "help" → return help text → END
  └── fallback → general LLM response → END
```

**State definition provided:**
```python
class ConversationState(TypedDict):
    messages: list[BaseMessage]
    intent: str | None          # "status", "search", "add", "help", "general"
    tool_results: list[dict]
    response: str | None
```

**Missing implementation details:**

#### Node implementations
The spec describes the flow but doesn't show:
- How `parse_intent` uses the LLM to classify user messages
- How `call tools` integrates with LangGraph's tool-calling mechanism
- How `format_response` constructs the final natural language response
- How `confirm with user` implements human-in-the-loop interrupts

#### Graph wiring
No code showing how to assemble the graph in LangGraph 1.x:
```python
# Missing from spec:
graph = StateGraph(ConversationState)
graph.add_node("parse_intent", parse_intent_node)
graph.add_node("call_tools", call_tools_node)
# ... edges, conditional routing, etc.
```

#### LangGraph approach unclear
The spec mentions both "create_react_agent" and custom StateGraph but doesn't choose:
- Should MVP use `create_react_agent` (easier, less control) or custom StateGraph (more work, full control)?
- The flow diagram suggests a custom StateGraph with explicit routing, but spec also mentions "react_agent"

**Research findings on LangGraph 1.x:**
- LangGraph 1.x uses `StateGraph` with TypedDict state
- Nodes return dict with state updates (not full state)
- Conditional edges use functions that return node names
- Prebuilt `create_react_agent` exists for common agent patterns
- Tool calling is handled via `ToolNode` and `tools_condition` built-in functions

**MODERATE GAP #2:**
**What Codex needs:** Either (a) an example graph implementation showing one complete flow, or (b) an explicit decision on whether to use `create_react_agent` vs custom StateGraph.

**Recommendation:**
Add a "Graph Implementation Pattern" section:
```python
from langgraph.graph import StateGraph, START, END
from langgraph.prebuilt import ToolNode, tools_condition

def route_intent(state: ConversationState) -> str:
    """Route based on parsed intent."""
    if state["intent"] == "status":
        return "call_tools"
    elif state["intent"] == "search":
        return "call_tools"
    # ... other cases

# Graph assembly
graph = StateGraph(ConversationState)
graph.add_node("parse_intent", parse_intent_node)
graph.add_node("call_tools", ToolNode(tools))
graph.add_node("format_response", format_response_node)

graph.add_edge(START, "parse_intent")
graph.add_conditional_edges("parse_intent", route_intent)
# ... rest of graph
```

---

### 3. OpenAI-Compatible API

**Verdict: GAP - Critical**

The spec says "implement /v1/chat/completions with SSE streaming" but provides no details about the actual SSE format expected by Open WebUI.

**Spec states:**
```python
# POST /v1/chat/completions
# GET /v1/models
```

**Missing critical details:**

#### SSE event format
Open WebUI expects a specific SSE format for chat completions. The spec doesn't specify:
- Event names: `data:`, `event:` prefixes
- Delta format: How to stream tokens incrementally
- Finish event: When to send `[DONE]` marker
- Chunk structure: Should each SSE chunk be a complete JSON object or a delta?

**Expected format (based on OpenAI API):**
```python
# Each SSE chunk:
data: {"id": "chatcmpl-123", "choices": [{"delta": {"content": "Hello"}}], ...}

# Final chunk:
data: [DONE]
```

#### FastAPI streaming pattern
No example of how to implement SSE in FastAPI:
- Should use `StreamingResponse` with `sse-starlette`?
- How to handle tool calls in streaming context?
- Event loop management for async tool execution

#### Response schema for Open WebUI
Open WebUI may expect specific fields:
- `id`: Chat completion ID
- `object`: "chat.completion.chunk"
- `created`: Unix timestamp
- `model`: "media-agent" (as spec says)
- `choices`: Array with `delta.content`
- `finish_reason`: "stop" or "tool_calls"

**CRITICAL GAP #3:**
**What Codex needs:** Exact SSE format expected by Open WebUI, including:
1. Example of 2-3 sequential SSE chunks
2. Final `[DONE]` chunk format
3. How tool calls are represented in streaming response
4. Complete FastAPI endpoint example

**Current state:** Codex would need to guess the format and likely get it wrong, requiring multiple iterations to match Open WebUI's expectations.

**Recommendation:**
Add a "OpenAI API Compatibility" section with:
```python
from fastapi import FastAPI
from sse_starlette.sse import EventSourceResponse

async def stream_chat_completion(request: ChatCompletionRequest):
    """Stream chat completions in OpenAI-compatible SSE format."""
    
    async def generate():
        chunk_id = "chatcmpl-123"
        created = int(time.time())
        
        # Send initial response
        yield f"data: {json.dumps({
            'id': chunk_id,
            'object': 'chat.completion.chunk',
            'created': created,
            'model': 'media-agent',
            'choices': [{
                'index': 0,
                'delta': {'role': 'assistant', 'content': ''},
                'finish_reason': None
            }]
        })}\n\n"
        
        # Stream tokens
        async for token in llm_stream_tokens(request.messages, request.tools):
            yield f"data: {json.dumps({
                'id': chunk_id,
                'object': 'chat.completion.chunk',
                'created': created,
                'model': 'media-agent',
                'choices': [{
                    'index': 0,
                    'delta': {'content': token},
                    'finish_reason': None
                }]
            })}\n\n"
        
        # Final chunk
        yield f"data: {json.dumps({
            'id': chunk_id,
            'object': 'chat.completion.chunk',
            'created': created,
            'model': 'media-agent',
            'choices': [{
                'index': 0,
                'delta': {},
                'finish_reason': 'stop'
            }]
        })}\n\n"
        
        yield "data: [DONE]\n\n"
    
    return EventSourceResponse(generate())
```

---

### 4. Ollama Integration

**Verdict: READY - Minor Gaps**

The spec's Ollama integration details are mostly complete with minor implementation gaps.

**Spec provides:**
```python
class MediaLLM:
    def __init__(self, config):
        self.primary = OllamaClient(
            url=config.ollama_url,      # http://host.docker.internal:11435
            model=config.ollama_model   # qwen2.5:7b
        )
```

**What's correct:**
- Model choice: Qwen 2.5 7B is well-documented for tool calling
- URL pattern: `host.docker.internal` is correct for Docker-to-host communication
- Fallback pattern: Local-first with hosted fallback is sound architecture

**Minor gaps:**

#### Tool calling API format
Spec doesn't show exact tool calling request format for Ollama:
```python
# Missing example:
async def call(self, messages, tools):
    response = await self.client.chat(
        model=self.model,
        messages=messages,
        tools=[{
            "type": "function",
            "function": {
                "name": "search_tv",
                "description": "Search for TV shows",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "query": {"type": "string"}
                    },
                    "required": ["query"]
                }
            }
        }]
    )
```

#### Parallel tool calls
Ollama's tool calling supports parallel calls in single response. Spec doesn't specify:
- Should the agent support parallel tool execution?
- Or serial execution (one tool at a time)?
- How to handle errors in parallel tool calls?

**Known failure modes for Ollama tool calling:**
1. **Tool name mismatch:** Ollama is case-sensitive on tool names
2. **Missing required params:** Ollama validates against tool schema before calling
3. **Timeout on long operations:** Ollama's default timeout may be too short for slow network APIs
4. **Schema validation:** Ollama rejects malformed tool schemas

**MINOR GAP #4:**
**What Codex needs:** Example tool calling integration showing:
- Tool schema format expected by Ollama
- Response parsing for tool_calls field
- Error handling for tool call failures

**Recommendation:**
Add example to LLM Engine section:
```python
# Tool calling with Ollama
def format_tools_for_ollama(tools: list[Tool]) -> list[dict]:
    """Format LangGraph tools for Ollama's tool calling API."""
    return [{
        "type": "function",
        "function": {
            "name": tool.name,
            "description": tool.description,
            "parameters": tool.args_schema.model_json_schema()
        }
    } for tool in tools]

# Response parsing
def parse_tool_calls(response: OllamaResponse) -> list[ToolCall]:
    """Extract tool calls from Ollama response."""
    if not response.message.tool_calls:
        return []
    return [ToolCall(
        id=call.id,
        name=call.function.name,
        arguments=json.loads(call.function.arguments)
    ) for call in response.message.tool_calls]
```

---

### 5. Configuration

**Verdict: READY - No Gaps**

The Pydantic Settings configuration pattern in the spec is correct and complete.

**Spec shows:**
```yaml
services:
  sonarr:
    url: "http://<YOUR_NAS_IP>:8989"
    api_key: "${SONARR_API_KEY}"
  radarr:
    url: "http://<YOUR_NAS_IP>:8310"
    api_key: "${RADARR_API_KEY}"
```

**How Pydantic Settings handles this:**

Pydantic Settings 2.0+ supports environment variable substitution via:
1. **Direct env var loading:** Use `Field(env="SONARR_API_KEY")` to map env vars to fields
2. **Pydantic's env file support:** Load from `.env` file automatically
3. **Custom substitution:** Use a custom `SettingsConfigDict` with `env_file=".env"`

**Pattern to use:**
```python
from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

class SonarrSettings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_prefix="SONARR_")
    
    url: str = Field(default="http://localhost:8989")
    api_key: str = Field(..., env="SONARR_API_KEY")

# Or load from YAML and substitute:
import os
import yaml

def load_config(path: str) -> dict:
    with open(path) as f:
        config = yaml.safe_load(f)
    
    # Substitute ${VAR} with env vars
    def substitute(value):
        if isinstance(value, str):
            for match in re.finditer(r'\$\{([^}]+)\}', value):
                env_var = match.group(1)
                if env_var in os.environ:
                    value = value.replace(match.group(0), os.environ[env_var])
            return value
        elif isinstance(value, dict):
            return {k: substitute(v) for k, v in value.items()}
        elif isinstance(value, list):
            return [substitute(v) for v in value]
        return value
    
    return substitute(config)
```

**Spec is correct:** The `${ENV_VAR}` pattern in YAML combined with custom substitution logic is a valid approach.

---

### 6. Missing Details

**Verdict: GAP - Multiple Minor to Moderate Gaps**

### Gaps that would require Codex to make decisions:

#### CRITICAL Gaps

**1. Tool result formatting for natural language responses**
- **Issue:** When a tool returns structured data (e.g., list of TV shows), how should this be formatted for the LLM to generate natural language?
- **Options:** 
  - Pass raw JSON to LLM with "explain this data" prompt
  - Convert to markdown table before passing to LLM
  - Write format-specific converters per tool
- **Impact:** Codex will choose one approach arbitrarily; user expectations may differ

**2. Error handling strategy**
- **Issue:** When an API call fails (401, 404, 500), what should the agent do?
- **Options:**
  - Return error message to user
  - Retry automatically with exponential backoff
  - Ask user to check configuration
  - Fall back to alternate endpoint
- **Impact:** Critical for production reliability; spec should define policy

**3. "Confirm with user" implementation**
- **Issue:** Spec shows "confirm with user" in graph flow but doesn't specify how this works for CLI vs API interfaces
- **Options:**
  - CLI: Prompt user for y/n input
  - API: Return special "confirmation_required" response type
  - Both: Require human-in-the-loop interrupt in LangGraph
- **Impact:** Different interfaces need different confirmation mechanisms

#### MODERATE Gaps

**4. Tool schema definitions**
- **Issue:** Spec lists tool names but doesn't define the Pydantic schemas for tool arguments
- **Example:** `add_tv_show(tvdb_id, quality_profile_id=1, monitored=True)` needs schema:
  ```python
  class AddTVShowInput(BaseModel):
      tvdb_id: int
      quality_profile_id: int = 1
      monitored: bool = True
  ```
- **Impact:** Codex will need to infer schemas from tool descriptions

**5. LLM system prompts**
- **Issue:** Spec mentions prompts exist in `config/prompts/` but doesn't provide example content
- **Impact:** Codex will generate generic prompts that may not match expected behavior

**6. Health check behavior**
- **Issue:** `check_all_health()` returns what? Success/failure boolean? Structured report?
- **Impact:** Unclear what tool caller should expect

**7. Queue status format**
- **Issue:** `get_queue_status()` returns what? JSON? Text summary? Items by service?
- **Impact:** Formatting for user display unclear

**8. Docker network configuration**
- **Issue:** Spec uses `host.docker.internal` but doesn't verify this works on all platforms
- **Impact:** May need fallback for non-Docker Desktop environments

**9. Streaming vs non-streaming modes**
- **Issue:** Should API support both streaming and non-streaming responses?
- **Impact:** Open WebUI requires streaming; CLI may prefer non-streaming

**10. Tool timeout handling**
- **Issue:** What timeout value for slow APIs? How to communicate timeout to user?
- **Impact:** User experience; default timeouts may be too short/long

**11. Rate limiting**
- **Issue:** Should agent implement rate limiting for API calls?
- **Impact:** May trigger bans on Servarr services if not rate-limited

#### MINOR Gaps

**12. Logging strategy**
- **Issue:** What to log? Tool calls? API responses? Errors only?
- **Impact:** Debugging vs privacy concerns

**13. Metrics/monitoring**
- **Issue:** Should agent expose metrics endpoint? What metrics?
- **Impact:** Production observability

**14. Graceful shutdown**
- **Issue:** How to handle in-flight operations on shutdown?
- **Impact:** Data loss vs incomplete operations

**15. Cache strategy**
- **Issue:** Should agent cache API responses? TTL?
- **Impact:** Performance vs staleness

**16. Version compatibility**
- **Issue:** Which Sonarr/Radarr/Emby versions is agent compatible with?
- **Impact:** API compatibility breaks

**17. Upgrade/migration**
- **Issue:** How to handle config schema changes between versions?
- **Impact:** Long-term maintenance

**18. Error message localization**
- **Issue:** Should error messages be localized?
- **Impact:** Non-English users

---

## Summary of Gaps by Severity

### CRITICAL Gaps (Blockers - Must Resolve)

| # | Area | Gap | Recommendation |
|---|------|-----|----------------|
| 1 | API Clients | No implementation examples for Sonarr/Radarr/Emby | Add 1 complete tool implementation per service |
| 2 | OpenAI API | SSE format for streaming not specified | Add exact SSE chunk format example |
| 3 | Tool Formatting | How to format tool results for natural language | Define result formatting strategy |

### MODERATE Gaps (Will Require Decisions)

| # | Area | Gap | Recommendation |
|---|------|-----|----------------|
| 4 | Graph | Custom StateGraph vs create_react_agent choice | Explicitly choose one approach |
| 5 | Error Handling | No error handling strategy defined | Define retry policy and user communication |
| 6 | Confirmation | "Confirm with user" implementation undefined | Specify CLI vs API confirmation flow |
| 7 | Tool Schemas | Pydantic schemas not defined | Add schema definitions for all 20 tools |
| 8 | System Prompts | Example prompts not provided | Add example system prompts |
| 9 | Health Check | Return format unclear | Define response schema |
| 10 | Queue Status | Return format unclear | Define response schema |
| 11 | Rate Limiting | Not specified | Define rate limiting requirements |

### MINOR Gaps (Acceptable Defaults)

| # | Area | Gap | Acceptable Default |
|---|------|-----|-------------------|
| 12 | Logging | No logging strategy defined | Log tool calls and errors only |
| 13 | Metrics | No monitoring specified | No metrics in MVP |
| 14 | Shutdown | No graceful shutdown defined | In-flight ops complete, then exit |
| 15 | Caching | No cache strategy defined | No caching in MVP |
| 16 | Versioning | No compatibility matrix | Compatible with latest stable |
| 17 | Migration | No migration strategy | Manual config updates |
| 18 | Localization | No localization | English only |

---

## Recommendations for Codex Readiness

### Before Delegating to Codex:

1. **Resolve Critical Gaps:**
   - Add API client implementation examples for Sonarr, Radarr, Emby (3 examples)
   - Add SSE streaming format example for OpenAI-compatible API
   - Define tool result formatting strategy

2. **Document Implementation Choices:**
   - State: "Use custom StateGraph, not create_react_agent" or vice versa
   - Define error handling policy (retry 3x with exponential backoff)
   - Define confirmation flow (CLI: input(), API: return confirmation_required)

3. **Add Tool Schemas:**
   - Create `schemas.py` with all 20 tool input/output models
   - Include validation rules and default values

### Acceptable to Delegate as-is:

- Docker configuration (service URLs are correct)
- Pydantic Settings configuration (pattern is valid)
- Ollama integration (add minor example, but core is correct)
- Directory structure (well-defined)

### Expected Codex Decisions (Accept to Leave Unspecified):

- Library choices: Codex will choose httpx over requests, specific error message formats
- Logging levels: Codex will choose INFO vs DEBUG
- Retry backoff timing: Codex will choose specific intervals
- Timeout values: Codex will choose 30s or 60s defaults

---

## Conclusion

**The spec is approximately 70% ready for Codex implementation.**

**Strengths:**
- Clear architecture and component boundaries
- Well-defined scope and phased approach
- Solid directory structure and containerization plan
- Correct usage patterns for Pydantic, Docker, LangGraph

**Weaknesses:**
- Lacks concrete implementation examples
- Missing API integration details
- No error handling or retry strategies
- OpenAI API SSE format unspecified
- Tool schemas not defined

**Estimated impact:**
- With critical gaps resolved: Codex could implement MVP in 2-3 days
- With current gaps: Codex would need 4-5 days plus iteration cycles to guess formats and fix incompatibilities

**Recommendation:** Spend 4-6 hours adding implementation examples and clarifying the critical gaps before delegating to Codex. This will save significant iteration time and ensure the implementation matches expectations.