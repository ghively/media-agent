"""Tests for token-level streaming: the stream-safe think filter and the
end-to-end token path through a real agent graph."""
import asyncio

from langchain_core.messages import AIMessage
from langchain_core.tools import tool

from src.llm.postprocess import ThinkStreamFilter


def _feed_all(chunks):
    f = ThinkStreamFilter()
    out = "".join(f.feed(c) for c in chunks)
    return out + f.flush()


def test_plain_text_passes_through():
    assert _feed_all(["Hello ", "world"]) == "Hello world"


def test_whole_think_block_suppressed():
    assert _feed_all(["<think>secret</think>answer"]) == "answer"


def test_think_block_split_across_chunks():
    assert _feed_all(["<th", "ink>sec", "ret</th", "ink>ans", "wer"]) == "answer"


def test_tag_split_at_every_position():
    text = "before<think>hidden</think>after"
    for i in range(1, len(text)):
        assert _feed_all([text[:i], text[i:]]) == "beforeafter", f"split at {i}"


def test_unclosed_think_suppressed_to_end():
    assert _feed_all(["visible<think>never closes", " more thinking"]) == "visible"


def test_lt_that_is_not_a_tag_is_emitted():
    assert _feed_all(["a < b and a <t", "ag> done"]) == "a < b and a <tag> done"


def test_multiple_blocks():
    assert _feed_all(["a<think>1</think>b<thinking>2</thinking>c"]) == "abc"


def test_token_streaming_end_to_end(test_settings):
    """Full agent graph via the real _stream_response in token mode: tool
    calls emit nothing, the think block is filtered, the answer streams."""
    import src.interfaces.openai_api as api
    from src.interfaces.openai_api import _stream_response, ChatMessage
    from langchain_core.language_models import BaseChatModel
    from langchain_core.messages import AIMessageChunk
    from langchain_core.outputs import ChatGeneration, ChatGenerationChunk, ChatResult

    @tool
    async def search_tv(query: str) -> str:
        """Search for TV shows by name."""
        return "1. Severance (2022)"

    # turn 1: pure tool-call chunk; turn 2: think block + answer, split into
    # awkward token boundaries (tag split across chunks)
    scripts = [
        [AIMessageChunk(content="", tool_call_chunks=[
            {"name": "search_tv", "args": '{"query": "severance"}',
             "id": "c1", "index": 0, "type": "tool_call_chunk"}])],
        [AIMessageChunk(content=piece) for piece in
         ["<th", "ink>found", " it</thi", "nk>Found ", "Severance ", "(2022). ", "Add it?"]],
    ]

    class ScriptedStreamModel(BaseChatModel):
        turn: int = 0

        @property
        def _llm_type(self):
            return "scripted"

        def bind_tools(self, tools, **kwargs):
            return self

        def _stream(self, messages, stop=None, run_manager=None, **kwargs):
            chunks = scripts[self.turn]
            self.turn += 1
            for chunk in chunks:
                yield ChatGenerationChunk(message=chunk)

        def _generate(self, messages, stop=None, run_manager=None, **kwargs):
            full = None
            for chunk in scripts[self.turn]:
                full = chunk if full is None else full + chunk
            self.turn += 1
            return ChatResult(generations=[ChatGeneration(message=full)])

    from langchain.agents import create_agent
    api._agent = create_agent(ScriptedStreamModel(), tools=[search_tv])
    try:
        async def run():
            chunks = []
            async for sse in _stream_response([ChatMessage(role="user", content="find severance")]):
                chunks.append(sse)
            return chunks

        raw = asyncio.run(run())
    finally:
        api._agent = None

    # reassemble the delta contents from the SSE chunks
    import json
    text = ""
    for sse in raw:
        body = sse.removeprefix("data: ").strip()
        if not body or body == "[DONE]":
            continue
        payload = json.loads(body)
        text += payload["choices"][0]["delta"].get("content", "")

    assert text == "Found Severance (2022). Add it?"
    assert "found it" not in text  # think content filtered mid-stream
    assert "search_tv" not in text  # tool call emitted nothing
    assert any("[DONE]" in c for c in raw)
    # multiple content chunks prove it actually streamed token-by-token
    content_chunks = [c for c in raw if '"content"' in c]
    assert len(content_chunks) > 1
