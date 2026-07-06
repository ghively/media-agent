"""Unit tests for user-facing output cleaning."""
import json

from langchain_core.messages import AIMessage

from src.llm.postprocess import clean_response, message_text, strip_reasoning


def test_strips_closed_think_block():
    assert strip_reasoning("<think>internal</think>answer") == "answer"


def test_strips_multiple_and_multiline_blocks():
    text = "<think>a\nb</think>Hello <thinking>c</thinking>world"
    assert strip_reasoning(text) == "Hello world"


def test_strips_unclosed_think_block():
    assert strip_reasoning("<think>model got cut off") == ""


def test_strips_tool_call_markup():
    text = '<tool_call>{"name": "x"}</tool_call>The answer is 4.'
    assert strip_reasoning(text) == "The answer is 4."


def test_plain_text_untouched():
    assert strip_reasoning("✅ Added 'Severance'") == "✅ Added 'Severance'"


def test_raw_tool_call_json_replaced_with_notice():
    msg = AIMessage(content=json.dumps({"name": "search_tv", "arguments": {"query": "x"}}))
    assert "did not produce a readable answer" in clean_response(msg)


def test_empty_after_stripping_replaced_with_notice():
    msg = AIMessage(content="<think>only thoughts</think>")
    assert "did not produce a readable answer" in clean_response(msg)


def test_content_block_lists_extract_text_only():
    msg = AIMessage(content=[
        {"type": "text", "text": "hello"},
        {"type": "thinking", "thinking": "zzz"},
    ])
    assert clean_response(msg) == "hello"


def test_message_text_handles_plain_string():
    assert message_text(AIMessage(content="hi")) == "hi"
