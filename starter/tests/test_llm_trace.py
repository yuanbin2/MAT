"""trace 记录完整模型请求与原始响应，且绝不落 Key。

直接对 LLMClient 打桩（不联网），检查写进 trace 的记录内容。
"""

from __future__ import annotations

import json

import pytest

from kbqa import llm

SECRET = "sk-supersecret-abcdef123456"


class FakeResponse:
    def __init__(self, status_code: int, text: str) -> None:
        self.status_code = status_code
        self.text = text

    def json(self):
        return json.loads(self.text)


def _patch(monkeypatch, status_code, text):
    calls = []

    def fake_post(url, json=None, headers=None, timeout=None):  # noqa: A002
        calls.append({"url": url, "body": json, "headers": headers})
        return FakeResponse(status_code, text)

    monkeypatch.setattr(llm.httpx, "post", fake_post)
    return calls


def test_trace_keeps_full_request_and_response(monkeypatch):
    payload = {
        "choices": [
            {
                "finish_reason": "stop",
                "message": {
                    "role": "assistant",
                    "content": "净营业额是 162414 元。",
                    "reasoning_content": "先查库再回答。",
                },
            }
        ],
        "usage": {"prompt_tokens": 12, "completion_tokens": 8},
    }
    calls = _patch(monkeypatch, 200, json.dumps(payload, ensure_ascii=False))

    messages = [
        {"role": "system", "content": "系统提示词内容"},
        {"role": "user", "content": "7 月营业额是多少"},
    ]
    tools = [
        {
            "type": "function",
            "function": {"name": "query_metrics", "description": "查指标", "parameters": {}},
        }
    ]
    records = []
    client = llm.LLMClient("https://api.deepseek.com", SECRET, "deepseek-flash")
    reply = client.chat(messages, tools, on_call=records.append)

    assert reply.content == "净营业额是 162414 元。"
    record = records[0]

    # 完整请求：每一轮消息与完整工具定义都在，且能原样解析回来。
    replayed = json.loads(record["request"])
    assert replayed["messages"] == messages
    assert replayed["tools"] == tools
    assert "系统提示词内容" in record["request"]
    assert "query_metrics" in record["request"]

    # 完整原始响应，含 reasoning_content 与 usage。
    assert record["response"] == json.dumps(payload, ensure_ascii=False)
    assert "reasoning_content" in record["response"]
    assert record["response_bytes"] == len(json.dumps(payload, ensure_ascii=False).encode("utf-8"))

    # 到 HTTP 层的 Authorization 头确实带着 Key（功能正常）……
    assert calls[0]["headers"]["Authorization"] == "Bearer %s" % SECRET
    # ……但它绝不能出现在 trace 记录里。
    blob = json.dumps(record, ensure_ascii=False)
    assert SECRET not in blob
    assert "Bearer " + SECRET not in blob


def test_error_detail_masks_api_key(monkeypatch):
    error_body = json.dumps(
        {"error": {"message": "invalid api key %s" % SECRET, "code": "invalid_api_key"}}
    )
    _patch(monkeypatch, 401, error_body)

    records = []
    client = llm.LLMClient("https://api.deepseek.com", SECRET, "deepseek-flash")
    with pytest.raises(llm.LLMError):
        client.chat([{"role": "user", "content": "hi"}], on_call=records.append)

    record = records[0]
    assert record["error"] == "http_401"
    blob = json.dumps(record, ensure_ascii=False)
    assert SECRET not in blob
    assert "sk-***" in blob or "***" in blob


def test_no_authorization_header_recorded(monkeypatch):
    payload = {"choices": [{"finish_reason": "stop", "message": {"content": "ok"}}]}
    _patch(monkeypatch, 200, json.dumps(payload))

    records = []
    client = llm.LLMClient("https://api.deepseek.com", SECRET, "deepseek-flash")
    client.chat([{"role": "user", "content": "hi"}], on_call=records.append)

    record = records[0]
    assert "Authorization" not in json.dumps(record, ensure_ascii=False)
    # 只记录 endpoint 与请求体，不记录请求头
    assert record["endpoint"].endswith("/chat/completions")


# -- 模型异常的所有路径都必须脱敏 -----------------------------------------------


def test_bad_json_echoing_key_is_masked(monkeypatch):
    """响应不是合法 JSON、且正文里回显了 Key —— 记录与异常都不能带 Key。"""
    raw = "invalid api key %s\n<html>not json</html>" % SECRET
    records = []
    _patch(monkeypatch, 200, raw)

    client = llm.LLMClient("https://api.deepseek.com", SECRET, "deepseek-flash")
    with pytest.raises(llm.LLMError) as info:
        client.chat([{"role": "user", "content": "hi"}], on_call=records.append)

    assert SECRET not in str(info.value)
    assert SECRET not in json.dumps(records[0], ensure_ascii=False)
    assert records[0]["error"] == "bad_json"


def test_timeout_and_transport_details_are_masked(monkeypatch):
    def fake_post(url, json=None, headers=None, timeout=None):  # noqa: A002
        raise llm.httpx.ConnectError("connect failed with key %s" % SECRET)

    monkeypatch.setattr(llm.httpx, "post", fake_post)
    records = []
    client = llm.LLMClient("https://api.deepseek.com", SECRET, "deepseek-flash")
    with pytest.raises(llm.LLMError) as info:
        client.chat([{"role": "user", "content": "hi"}], on_call=records.append)
    assert SECRET not in str(info.value)
    assert SECRET not in json.dumps(records[0], ensure_ascii=False)


def test_trace_store_redacts_on_save():
    from kbqa.trace import Trace, TraceStore

    def redactor(payload):
        if isinstance(payload, str):
            return llm.redact_secret(payload, SECRET)
        if isinstance(payload, dict):
            return {key: redactor(value) for key, value in payload.items()}
        if isinstance(payload, list):
            return [redactor(item) for item in payload]
        return payload

    store = TraceStore()
    trace = Trace("t-redact", "q")
    trace.step("boom", {"detail": "模型回显了 %s" % SECRET})
    store.save(trace, redactor=redactor)
    payload = store.get("t-redact")
    blob = json.dumps(payload, ensure_ascii=False)
    assert SECRET not in blob
    assert "***" in blob


def test_service_trace_masks_key_on_llm_error(monkeypatch):
    """端到端：live 模式下模型抛错并把 Key 放进 detail，/api/trace 里也不能出现 Key。"""
    from dataclasses import replace

    import kbqa.service as service_module
    from kbqa.config import load_settings
    from kbqa.llm import LLMError
    from kbqa.service import Service

    base = load_settings()
    settings = replace(
        base,
        llm_base_url="https://api.deepseek.com",
        llm_api_key=SECRET,
        llm_model="deepseek-flash",
    )

    class Boom:
        def __init__(self, *args, **kwargs):
            pass

        def chat_with_retry(self, *args, **kwargs):
            raise LLMError("bad_json", '模型返回的不是合法 JSON：{"echo": "%s"}' % SECRET)

    monkeypatch.setattr(service_module, "LLMClient", Boom)

    service = Service(settings)
    out = service.chat("s-live", "7 月整体的净营业额是多少？")
    trace = service.get_trace(out["trace_id"])

    assert out["answer_type"] == "refusal"
    assert SECRET not in json.dumps(out, ensure_ascii=False)
    assert SECRET not in json.dumps(trace, ensure_ascii=False)
    # 但失败原因仍要可见（可观察性不能因为脱敏而丢失）
    assert trace["errors"], "错误必须留在 trace 里"
    assert "合法 JSON" in json.dumps(trace, ensure_ascii=False)
