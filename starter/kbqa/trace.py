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

#: 工具调用刚记下、还不知道算不算被采纳时的占位原因（回答定稿后会被 replace）。
PENDING_REASON = "待回答定稿后核对是否被采用"

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
        pending: bool = False,
        evidence_result: Any = None,
        retrieved_doc_ids: Optional[list] = None,
    ) -> dict:
        """记录一次真实执行过的工具/检索调用。

        ``accepted`` 表示结果是否进入最终回答依据；``entered`` 说明进了哪里
        （``data_evidence`` / ``citations``）。因 Plan 范围不一致等原因被拒绝时
        ``status="rejected"`` 且带 ``reject_reason``，绝不标成已采纳的证据。

        ``pending=True`` 给"此刻还不知道算不算数"的调用用。检索执行成功、返回了候选片段、
        最终真的被引用，这是**三件不同的事**；数据库工具"查到了真实数字"和"这个数字进了
        最终回答"也不是一回事。这类条目先记成未采纳，等回答定稿后由 ``reconcile()``
        按最终 ``citations`` / ``data_evidence`` 回填——避免出现"面板说引用了、回答里其实没有"。
        """
        entry: dict[str, Any] = {
            "tool": tool,
            "params": params,
            "status": status,
            # 未定稿前一律 accepted=False：宁可先显示"未采纳"，也不能提前声称被采纳。
            "accepted": False if pending else accepted,
        }
        if pending:
            entry["pending"] = True
            entry["reject_reason"] = reject_reason or PENDING_REASON
        entry["took_ms"] = round(took_ms, 1) if took_ms is not None else None
        if entered:
            entry["entered"] = entered
        if reject_reason and not pending:
            entry["reject_reason"] = reject_reason
        if source:
            entry["source"] = source
        if evidence_result is not None:
            # 私有字段：只用于定稿后按对象身份核对，不进 /api/trace 的返回。
            entry["_evidence_obj"] = evidence_result
        if retrieved_doc_ids is not None:
            entry["_doc_ids"] = [doc_id for doc_id in retrieved_doc_ids if doc_id]
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
                "detail": {"tool": tool, "status": status, "accepted": entry["accepted"]},
            }
        )
        return entry

    def reconcile(self, *, evidence: Any = None, citations: Any = None) -> int:
        """回答定稿后回填"待定"条目的采纳状态，返回改动的条目数。

        判定依据只有最终返回给调用方的那两份东西：``data_evidence`` 与 ``citations``。
        其它来源（问题原文、整篇文档、参数、曾经检索到过）都不算数。

        - 数据库/检查类：结果对象确实出现在最终证据里 → ``data_evidence``；
          否则不算采纳——模型可能改用了别的证据，或者本轮整体回退成了拒答。
        - ``search_kb``：执行成功且返回候选**不等于**被引用；只有最终引用里出现它命中过的
          doc_id 才算 ``citations``，否则说明是"检索到了但没用上"。
        """
        used = {id(item.get("result")) for item in (evidence or []) if isinstance(item, dict)}
        cited = {
            item.get("doc_id") for item in (citations or []) if isinstance(item, dict)
        }
        changed = 0
        for entry in self.tools:
            if not entry.pop("pending", False):
                continue
            changed += 1
            if entry.get("tool") == "search_kb":
                doc_ids = set(entry.get("_doc_ids") or [])
                if doc_ids & cited:
                    entry["accepted"] = True
                    entry["entered"] = "citations"
                    entry.pop("reject_reason", None)
                else:
                    entry["accepted"] = False
                    entry.pop("entered", None)
                    entry["reject_reason"] = (
                        "检索没有命中任何片段，没有可引用的依据"
                        if not doc_ids
                        else "检索到候选片段，但最终回答没有引用它们"
                    )
                continue
            obj = entry.get("_evidence_obj")
            if obj is not None and id(obj) in used:
                entry["accepted"] = True
                entry["entered"] = "data_evidence"
                entry.pop("reject_reason", None)
            else:
                entry["accepted"] = False
                entry.pop("entered", None)
                entry["reject_reason"] = (
                    "结果没有进入最终回答依据（本轮可能改用了其它证据，或已回退成拒答）"
                )
        return changed

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
            # 私有字段（_evidence_obj / _doc_ids）只用于定稿后核对，不外泄。
            "tools": [
                {key: value for key, value in entry.items() if not key.startswith("_")}
                for entry in self.tools
            ],
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
