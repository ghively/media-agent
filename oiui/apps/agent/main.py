"""
This is the main entry point for the agent.
It defines the workflow graph, state, tools, nodes and edges.
"""

import os
import warnings

from dotenv import load_dotenv
from fastapi import FastAPI
from fastapi.responses import JSONResponse
from copilotkit import CopilotKitMiddleware
from ag_ui_langgraph import add_langgraph_fastapi_endpoint
from deepagents import create_deep_agent

from oiui_agent.anthropic_compat import ConsecutiveSystemMessagesMiddleware
from oiui_agent.bounded_memory_saver import BoundedMemorySaver
from oiui_agent.model import build_model, RequestModelMiddleware, CredentialScopedModel
from oiui_agent.credentials import (
    CredentialsMiddleware,
    CredentialScopedAgent,
    current_credentials,
    validate_credentials,
)
from oiui_agent.visualization_router import JevVisualizationMiddleware
from oiui_agent.skill_backend import SKILL_SOURCES, build_agent_backend
from oiui_agent.todos import AgentState
from oiui_agent.plan import plan_visualization
from oiui_agent.prompt import SYSTEM_PROMPT
from oiui_agent.media_bridge import (
    MEDIA_PROMPT,
    MediaApprovalMiddleware,
    data_tools,
    load_media_tools,
)

load_dotenv()

agent = create_deep_agent(
    model=CredentialScopedModel(fallback=build_model(allow_unconfigured=True)),
    # media-agent's tools + JSON data tools for charts. The OIUI demo tools
    # (sample CSV, trip photos, todo list, login-form demo) are left out.
    tools=[*load_media_tools(), *data_tools, plan_visualization],
    middleware=[
        MediaApprovalMiddleware(),
        RequestModelMiddleware(),
        CopilotKitMiddleware(),
        JevVisualizationMiddleware(),
        ConsecutiveSystemMessagesMiddleware(),
    ],
    context_schema=AgentState,
    skills=SKILL_SOURCES,
    backend=build_agent_backend,
    checkpointer=BoundedMemorySaver(max_threads=200),
    system_prompt=MEDIA_PROMPT + SYSTEM_PROMPT,
)

app = FastAPI()
app.add_middleware(CredentialsMiddleware)


@app.post("/credentials/validate")
async def validate_provider_credentials():
    credentials = current_credentials.get()
    if credentials is None:
        return JSONResponse({"ok": False, "code": "invalid_keys"}, status_code=400)
    return await validate_credentials(credentials)


@app.get("/health")
def health():
    return {"status": "ok"}


add_langgraph_fastapi_endpoint(
    app=app,
    agent=CredentialScopedAgent(
        name="sample_agent",
        description="Media Agent on Open Intelligent UI (proof of concept)",
        graph=agent,
    ),
    path="/",
)

warnings.filterwarnings("ignore", category=UserWarning, module="pydantic")

if __name__ == "__main__":
    import uvicorn

    port = int(os.getenv("PORT", "8123"))
    # Localhost only by default: this agent can add and download media and has
    # no login of its own. Only the Next.js app needs to reach it.
    host = os.getenv("AGENT_HOST", "127.0.0.1")
    uvicorn.run("main:app", host=host, port=port, reload=True)
