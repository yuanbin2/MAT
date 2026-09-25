"""追踪：一次问答的每一步、耗时、错误都记下来，调试面板用。

设计要点（第四关）：

- **真实**：只记录实际发生的事——真跑过的工具、真返回的结果、真花掉的耗时。
  没有测量到的时间写 ``None``（面板显示「未记录」），不用 0 冒充。
- **不共享可变状态**：每次 ``/api/chat`` 新建一个 ``Trace``，由调用链以参数传递，
  没有任何模块级 ``current_trace``，并发请求不会串记录。
- **有界 + 脱敏持久化**：``TraceStore`` 落盘前过脱敏闸门，容量封顶，
  跨重启仍能按 ID 找回（内存没命中就回磁盘）。
"""

from __future__ import annotations

import json
import re
import threading
import time
import traceback
from collections import OrderedDict
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

#: 记录里单条文本的预览上限，避免把整份知识库/长响应塞进 trace。
PREVIEW_CHARS = 200
#: 工具结果预览上限（有界摘要，不是完整结果）。
TOOL_PREVIEW_CHARS = 400
#: trace 里模型请求/响应的长度兜底（正常一轮远小于它）。
MAX_LLM_TEXT = 200_000

_ID_RE = re.compile(r"^t-(\d{8})-(\d+)$")


@dataclass
class Trace:
    trace_id: str
    question: str
    session_id: Optional[str] = None
    mode: str = "mock"
    started_at: str = field(default_factory=lambda: datetime.now().isoformat(timespec="milliseconds"))
    steps: list[dict] = field(default_factory=list)
    errors: list[dict] = field(default_factory=list)
    llm_calls: list[dict] = field(default_factory=list)
    tools: list[dict] = field(default_factory=list)
    retrievals: list[dict] = field(default_factory=list)
    plan: dict = field(default_factory=dict)
    answer: dict = field(default_factory=dict)
    _t0: float = field(default_factory=time.perf_counter)

    def step(self, name: str, payload: Any = None, started: Optional[float] = None) -> None:
        now = time.perf_counter()
        self.steps.append(
            {
                "step": name,
                "at_ms": round((now - self._t0) * 1000, 1),
                "took_ms": round((now - started) * 1000, 1) if started else None,
                "detail": _bounded(payload),
            }
        )
        # 规划与检索另存一份结构化视图，面板按排查顺序取用。
        if name == "plan" and isinstance(payload, dict):
            self.plan = payload
        elif name == "search" and isinstance(payload, dict):
            self.retrievals.append(payload)

    def tool(
        self,
        *,
        tool: str,
        params: dict,
        status: str,
        result: Any = None,
        took_ms: Optional[float] = None,
        accepted: bool = False,
        reject_reason: Optional[str] = None,
        entered: str = "",
        source: str = "",
    ) -> None:
        """记录一次真实执行过的工具/检索调用。

        ``accepted`` 表示结果是否进入最终回答依据；``entered`` 说明进了哪里
        （``data_evidence`` / ``citations``）。因 Plan 范围不一致等原因被拒绝时
        ``status="rejected"`` 且带 ``reject_reason``，绝不标成已采纳的证据。
        """
        entry: dict[str, Any] = {
            "tool": tool,
            "params": params,
            "status": status,
            "took_ms": round(took_ms, 1) if took_ms is not None else None,
            "accepted": accepted,
        }
        if entered:
            entry["entered"] = entered
        if reject_reason:
            entry["reject_reason"] = reject_reason
        if source:
            entry["source"] = source
        if result is not None:
            try:
                blob = json.dumps(result, ensure_ascii=False, default=str)
            except (TypeError, ValueError):
                blob = str(result)
            entry["result_bytes"] = len(blob.encode("utf-8"))
            entry["result_preview"] = blob[:TOOL_PREVIEW_CHARS] + (
                "…（截断）" if len(blob) > TOOL_PREVIEW_CHARS else ""
            )
        self.tools.append(entry)
        self.steps.append(
            {
                "step": "tool",
                "at_ms": round((time.perf_counter() - self._t0) * 1000, 1),
                "took_ms": entry["took_ms"],
                "detail": {"tool": tool, "status": status, "accepted": accepted},
            }
        )

    def error(self, where: str, exc: BaseException) -> None:
        """真实原因要留下来：类型、消息、堆栈，一个都不少。"""
        self.errors.append(
            {
                "where": where,
                "type": type(exc).__name__,
                "message": str(exc),
                "traceback": traceback.format_exc(limit=8),
            }
        )

    def llm(self, payload: dict) -> None:
        self.llm_calls.append(payload)

    def as_dict(self) -> dict:
        return {
            "trace_id": self.trace_id,
            "session_id": self.session_id,
            "question": self.question,
            "mode": self.mode,
            "started_at": self.started_at,
            "total_ms": round((time.perf_counter() - self._t0) * 1000, 1),
            "plan": self.plan,
            "retrievals": self.retrievals,
            "tools": self.tools,
            "answer": self.answer,
            "model_called": bool(self.llm_calls),
            "llm_calls": self.llm_calls,
            "steps": self.steps,
            "errors": self.errors,
        }


def _bounded(value: Any) -> Any:
    """把超长文本截成预览，保持 JSON 可序列化。"""
    if isinstance(value, str):
        return value if len(value) <= PREVIEW_CHARS else value[:PREVIEW_CHARS] + "…"
    if isinstance(value, dict):
        return {key: _bounded(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_bounded(item) for item in value]
    return value


class TraceStore:
    """有界、可持久化的 trace 存储。

    - 内存里保留最近 ``capacity`` 条；
    - 落盘到 ``directory``（默认不落盘），文件名即 trace_id；
    - 跨重启：``new_id`` 从磁盘已有编号继续，不会重复；内存没命中就去磁盘找。
    """

    def __init__(self, capacity: int = 200, directory: Optional[Path] = None) -> None:
        self._data: "OrderedDict[str, dict]" = OrderedDict()
        self._lock = threading.Lock()
        self.capacity = capacity
        self.directory = Path(directory) if directory else None
        self._counter = 0
        self._seen: set[str] = set()
        if self.directory is not None:
            self.directory.mkdir(parents=True, exist_ok=True)
            self._load_existing()

    # -- 编号 -------------------------------------------------------------------

    def _load_existing(self) -> None:
        for path in self.directory.glob("t-*.json"):
            self._seen.add(path.stem)
            match = _ID_RE.match(path.stem)
            if match:
                self._counter = max(self._counter, int(match.group(2)))
        self._prune()

    def new_id(self, today: str) -> str:
        with self._lock:
            while True:
                self._counter += 1
                candidate = "t-%s-%04d" % (today.replace("-", ""), self._counter)
                if candidate not in self._seen:
                    self._seen.add(candidate)
                    return candidate

    # -- 读写 -------------------------------------------------------------------

    def save(self, trace: Trace, redactor=None) -> None:
        payload = trace.as_dict()
        if redactor is not None:
            payload = redactor(payload)
        with self._lock:
            self._data[payload["trace_id"]] = payload
            self._data.move_to_end(payload["trace_id"])
            while len(self._data) > self.capacity:
                self._data.popitem(last=False)
        if self.directory is not None:
            self._write(payload)
            self._prune()

    def get(self, trace_id: str) -> Optional[dict]:
        with self._lock:
            hit = self._data.get(trace_id)
            if hit is not None:
                return hit
        if self.directory is None:
            return None
        path = self.directory / ("%s.json" % trace_id)
        if not path.exists():
            return None
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return None
        with self._lock:
            self._data[trace_id] = payload
            self._data.move_to_end(trace_id)
            while len(self._data) > self.capacity:
                self._data.popitem(last=False)
        return payload

    # -- 磁盘 -------------------------------------------------------------------

    @staticmethod
    def _safe_name(trace_id: str) -> bool:
        return bool(_ID_RE.match(trace_id))

    def _write(self, payload: dict) -> None:
        trace_id = payload.get("trace_id", "")
        if not self._safe_name(trace_id):
            return
        target = self.directory / ("%s.json" % trace_id)
        tmp = target.with_suffix(".json.tmp")
        try:
            tmp.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
            tmp.replace(target)
        except OSError:
            # 落盘失败不能让问答失败：内存里还留着这条记录。
            return

    def _prune(self) -> None:
        if self.directory is None:
            return
        files = sorted(
            self.directory.glob("t-*.json"), key=lambda path: (path.stat().st_mtime, path.name)
        )
        for path in files[: max(0, len(files) - self.capacity)]:
            try:
                path.unlink()
            except OSError:
                continue
