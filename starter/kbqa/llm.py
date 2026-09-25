"""Chat Completions 客户端，OpenAI 格式，目标是 DeepSeek 官方 API。

只 POST {LLM_BASE_URL}/chat/completions，地址原样拼接，不补 /v1。
配置只从 LLM_BASE_URL、LLM_API_KEY、LLM_MODEL 三个环境变量读。
空正文、异常 finish_reason、错误码、超时都抛成带原因的异常。
"""

from __future__ import annotations

import json
import re
import time
from dataclasses import dataclass
from typing import Any, Optional

import httpx

#: 契约 §7.3：思考也占输出额度，`max_tokens` 不设或不小于 2048。
MAX_TOKENS = 4096
#: 正常结束只有这两种。
GOOD_FINISH = ("stop", "tool_calls")
#: 这几类是暂时性的，值得重试一次。
RETRYABLE_STATUS = (429, 500, 503)
RETRYABLE_KINDS = ("empty_content", "insufficient_system_resource", "transport")
#: 账号侧限制的特征串：这类 403 重试多少次都一样，只能去控制台处理。
ACCOUNT_BLOCK_MARKERS = ("real-name verification", "realname", "real_name", "实名")
#: trace 里请求/响应的安全兜底长度；正常一轮远小于它，不会触发截断。
MAX_TRACE_TEXT = 200_000


def redact_secret(text: str, secret: str = "") -> str:
    """把文本里的密钥擦掉。所有会写进 trace / 回答的错误信息都必须过这一层。

    除了替换已知的 Key，还用正则兜底 ``Bearer …`` 与 ``sk-…`` 形态——
    模型或网关把 Key 回显在响应正文里（例如非法 JSON 的调试信息）时也擦得掉。
    """
    text = text or ""
    if secret:
        text = text.replace(secret, "***")
    text = re.sub(r"(?i)bearer\s+[A-Za-z0-9._\-]+", "Bearer ***", text)
    text = re.sub(r"sk-[A-Za-z0-9_\-]{6,}", "sk-***", text)
    return text


@dataclass
class LLMError(Exception):
    kind: str
    detail: str
    status: Optional[int] = None

    def __str__(self) -> str:  # pragma: no cover - 只用于日志
        return "%s: %s" % (self.kind, self.detail)

    @property
    def retryable(self) -> bool:
        return self.status in RETRYABLE_STATUS or self.kind in RETRYABLE_KINDS


@dataclass
class LLMReply:
    message: dict
    """assistant 消息原样，回传时整条塞回 messages（含 reasoning_content）。"""
    finish_reason: str
    content: str
    tool_calls: list[dict]
    elapsed: float


class LLMClient:
    def __init__(self, base_url: str, api_key: str, model: str, timeout: float = 120.0) -> None:
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.model = model
        self.timeout = timeout

    @property
    def endpoint(self) -> str:
        return self.base_url + "/chat/completions"

    def _body(self, messages: list[dict], tools: Optional[list[dict]]) -> dict:
        body: dict[str, Any] = {
            "model": self.model,
            "messages": messages,
            "max_tokens": MAX_TOKENS,
        }
        if tools:
            body["tools"] = tools
            body["tool_choice"] = "auto"
        return body

    def _mask(self, text: str) -> str:
        """写进 trace 前把密钥擦掉（双保险——Key 本来就不放进 body）。

        只擦认证信息，不改动提示词与模型输出，保证可观察性。
        """
        return redact_secret(text, self.api_key)

    def _clip(self, text: str) -> str:
        if len(text) <= MAX_TRACE_TEXT:
            return text
        return text[:MAX_TRACE_TEXT] + "…（trace 已截断，共 %d 字）" % len(text)

    def _record_request(self, body: dict) -> str:
        """完整记录请求体（含每一轮消息与工具定义），仅脱敏、不预览截断。"""
        return self._clip(self._mask(json.dumps(body, ensure_ascii=False)))

    def chat(
        self,
        messages: list[dict],
        tools: Optional[list[dict]] = None,
        timeout: Optional[float] = None,
        on_call: Optional[Any] = None,
    ) -> LLMReply:
        started = time.perf_counter()
        body = self._body(messages, tools)
        record: dict[str, Any] = {
            "endpoint": self.endpoint,
            "model": self.model,
            "messages": len(messages),
            "tools": len(tools or []),
            # 契约 §6/§7.2：trace 里要看得到发给模型的**完整**请求（提示词、
            # 工具定义、每一轮消息），只对 Key 脱敏，不做内容截断。
            "request": self._record_request(body),
            "prompt": _preview(json.dumps(messages, ensure_ascii=False)),
        }
        try:
            response = httpx.post(
                self.endpoint,
                json=body,
                headers={
                    "Authorization": "Bearer %s" % self.api_key,
                    "Content-Type": "application/json",
                },
                timeout=httpx.Timeout(timeout or self.timeout, connect=15.0),
            )
        except httpx.TimeoutException as exc:
            detail = self._mask("等待模型响应超时：%s" % exc)
            record.update(error="timeout", detail=detail)
            self._note(on_call, record, started)
            raise LLMError("timeout", detail) from exc
        except httpx.HTTPError as exc:
            detail = self._mask("调用模型失败：%s" % exc)
            record.update(error="transport", detail=detail)
            self._note(on_call, record, started)
            raise LLMError("transport", detail) from exc

        record["status"] = response.status_code
        # 契约 §6：模型**原始响应**也要留痕（脱敏后完整保存）。
        record["response"] = self._clip(self._mask(response.text))
        record["response_bytes"] = len(response.text.encode("utf-8"))
        if response.status_code != 200:
            # 400/401/402/422/429/500/503 都在这里变成结构化错误。
            detail = self._mask(_error_detail(response))
            kind = "http_error"
            if is_account_blocked(response.status_code, detail):
                # 实测过：免费额度要求先实名，403 正文写着 real-name verification。
                # 这不是代码问题也不是暂时故障——重试没用，得说清楚去哪儿处理。
                kind = "account_blocked"
            record.update(error="http_%d" % response.status_code, detail=detail, kind=kind)
            self._note(on_call, record, started)
            raise LLMError(kind, detail, status=response.status_code)

        # 服务繁忙时正文前面会有空行，json 解析要能跳过。
        try:
            payload = json.loads(response.text.strip() or "{}")
        except ValueError as exc:
            # 非 JSON 的响应正文可能回显了 Key（调试信息、错误页），
            # 记录与抛出的信息都必须先脱敏。
            detail = self._mask("模型返回的不是合法 JSON：%s" % response.text[:200])
            record.update(error="bad_json", detail=detail)
            self._note(on_call, record, started)
            raise LLMError("bad_json", detail) from exc

        choices = payload.get("choices") or []
        if not choices:
            record.update(error="no_choice")
            self._note(on_call, record, started)
            raise LLMError("no_choice", "模型响应里没有 choices")
        choice = choices[0]
        message = choice.get("message") or {}
        finish = choice.get("finish_reason") or ""
        content = message.get("content") or ""
        tool_calls = message.get("tool_calls") or []
        record.update(
            finish_reason=finish,
            content_chars=len(content),
            tool_calls=[call.get("function", {}).get("name") for call in tool_calls],
            has_reasoning=bool(message.get("reasoning_content")),
            usage=payload.get("usage"),
            # 契约 §6：模型原始输出也要留痕。思考过程只留在 trace 里，不进任何对外字段。
            raw_content=_preview(content),
            raw_reasoning=_preview(message.get("reasoning_content") or ""),
        )
        self._note(on_call, record, started)

        if finish not in GOOD_FINISH:
            # D11：length / content_filter / insufficient_system_resource / aborted 一律按错误处理。
            raise LLMError(finish or "unknown_finish", "模型异常结束：finish_reason=%s" % finish)
        if not content.strip() and not tool_calls:
            raise LLMError("empty_content", "模型返回了空正文（finish_reason=%s）" % finish)
        return LLMReply(
            message=message,
            finish_reason=finish,
            content=content,
            tool_calls=tool_calls,
            elapsed=time.perf_counter() - started,
        )

    def chat_with_retry(
        self,
        messages: list[dict],
        tools: Optional[list[dict]] = None,
        budget: Optional[float] = None,
        on_call: Optional[Any] = None,
    ) -> LLMReply:
        """暂时性故障重试一次，且只在时间预算够的时候重试。"""
        per_call = min(self.timeout, budget) if budget else self.timeout
        try:
            return self.chat(messages, tools, timeout=per_call, on_call=on_call)
        except LLMError as first:
            remaining = (budget - per_call) if budget else self.timeout
            if not first.retryable or remaining < 5:
                raise
            time.sleep(min(1.0, max(0.0, remaining / 60)))
            return self.chat(messages, tools, timeout=min(self.timeout, remaining), on_call=on_call)

    @staticmethod
    def _note(on_call, record: dict, started: float) -> None:
        if on_call is not None:
            record["took_ms"] = round((time.perf_counter() - started) * 1000, 1)
            on_call(record)


def _preview(text: str, limit: int = 4000) -> str:
    text = text or ""
    return text if len(text) <= limit else text[:limit] + "…（截断，共 %d 字）" % len(text)


def is_account_blocked(status: Optional[int], detail: str) -> bool:
    """判断是不是"账号侧限制"——与代码和暂时性故障都无关，重试无效。

    实测到的形态：`HTTP 403 ... real-name verification is required for your free
    step plan before calling this API`。这类失败会波及**每一道**走模型的题，
    如果不单独识别，面板/回答里只会显示"接口返回错误码 403"，看不出该怎么办。
    """
    if status != 403:
        return False
    lowered = (detail or "").lower()
    return any(marker.lower() in lowered for marker in ACCOUNT_BLOCK_MARKERS)


def _error_detail(response: httpx.Response) -> str:
    try:
        payload = response.json()
    except ValueError:
        return "HTTP %d：%s" % (response.status_code, response.text[:200])
    error = payload.get("error") if isinstance(payload, dict) else None
    if isinstance(error, dict):
        return "HTTP %d：%s（code=%s）" % (
            response.status_code,
            error.get("message", ""),
            error.get("code", ""),
        )
    return "HTTP %d：%s" % (response.status_code, json.dumps(payload, ensure_ascii=False)[:200])
