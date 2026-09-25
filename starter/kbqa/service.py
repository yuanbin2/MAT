"""把各个部件接起来：规划、取数、检索、作答。"""

from __future__ import annotations

import re
import sqlite3
import time
from typing import Any, Optional

from .answerer import Answerer
from .schemas import Answer
from .cleaning import build_clean_db
from .docfacts import DocFacts
from .config import Settings, load_settings
from .entities import Catalog
from .index import load_index
from .live import LiveEngine
from .llm import LLMClient, LLMError, redact_secret
from .planner import Planner
from .retriever import Retriever
from .sessions import SessionStore
from .sqlguard import fit_evidence
from .toolspec import TOOL_NAMES, TOOLS
from .tools import DataTools
from .trace import Trace, TraceStore

_ISO_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_INT_PARAMS = {"top_k", "limit"}


class Service:
    def __init__(self, settings: Optional[Settings] = None) -> None:
        self.settings = settings or load_settings()
        self.sessions = SessionStore()
        # 有界 + 脱敏的持久化 trace：跨重启仍能按 ID 找回。
        self.traces = TraceStore(directory=self.settings.traces_dir)
        self.rebuild(only_if_missing=True)

    # -- 启动与重建 -------------------------------------------------------------

    def rebuild(self, only_if_missing: bool = False) -> None:
        settings = self.settings
        if not only_if_missing or not settings.clean_db.exists():
            build_clean_db(settings.source_db, settings.clean_db)
        self.tools = DataTools(settings.clean_db)
        self.index = load_index(settings.kb_dir, settings.index_path, rebuild=not only_if_missing)
        self.retriever = Retriever(self.index, settings.today)
        self.catalog = Catalog(
            stores=self.tools.stores(), products=self.tools.products(), aliases=self.index.aliases
        )
        self.data_period = self.tools.data_period()
        self.facts = DocFacts(self.index)
        self.answerer = Answerer(
            self.tools, self.retriever, self.catalog, settings.today, self.data_period, self.facts
        )
        self.planner = Planner(self.catalog, settings.today, self.data_period, self._scout)

    def _scout(self, text: str) -> tuple[float, float]:
        """给一句话探底：它的词在知识库里有多少、检索最高分多少。

        越界判断只看这两个数，不看话题词表：知识库真讲这件事就一定照答。
        """
        result = self.retriever.search(text, top_k=1)
        return self.facts.vocab_coverage(text), (result.hits[0].score if result.hits else 0.0)

    # -- 只读接口 ---------------------------------------------------------------

    def health(self) -> dict:
        report = self.tools.cleaning_report()
        return {
            "status": "ok",
            "llm_mode": self.settings.llm_mode,
            # 契约 §1：kb_docs 是实际进入索引的文档数，不是目录里的文件数。
            "kb_docs": len(self.index.docs_meta),
            "kb_chunks": len(self.index.chunks),
            "valid_sales_rows": self.tools.valid_sales_rows(),
            "today": self.settings.today.isoformat(),
            "data_period": self.data_period,
            "cleaning_report": report,
            "index_key": self.index.key[:12],
            "kb_warnings": self.index.warnings,
        }

    def metrics_summary(self, start: str, end: str, store_id=None, product_id=None) -> dict:
        return self.tools.query_metrics(start, end, store_id, product_id)

    def metrics_daily(self, start: str, end: str, store_id=None, product_id=None) -> dict:
        return self.tools.daily_metrics(start, end, store_id, product_id)

    def retrieve(self, query: str, top_k: int = 5) -> dict:
        """契约 §4：片段够就恰好给 top_k 条，不够才少给。

        `top_k` 大于索引里的片段总数时按总数封顶——这正是契约允许少给的那种情况。
        """
        wanted = max(1, min(int(top_k or 5), len(self.index.chunks) or 1))
        result = self.retriever.search(query or "", top_k=wanted)
        return {"results": [hit.as_result() for hit in result.hits]}

    # -- 工具执行（live 模式下由模型驱动） ---------------------------------------

    def run_tool(self, name: str, params: dict) -> dict:
        if name not in TOOL_NAMES:
            return {"error": "没有这个工具：%s，可用工具：%s" % (name, "、".join(TOOL_NAMES))}
        schema = next(
            tool["function"]["parameters"] for tool in TOOLS if tool["function"]["name"] == name
        )
        cleaned: dict[str, Any] = {}
        for key, value in (params or {}).items():
            if key not in schema["properties"]:
                continue
            if key in _INT_PARAMS:
                try:
                    cleaned[key] = int(value)
                except (TypeError, ValueError):
                    return {"error": "参数 %s 应该是整数，收到 %r" % (key, value)}
                continue
            if value is None:
                continue
            text = str(value).strip()
            if key.startswith(("start", "end")) or key == "date":
                if not _ISO_DATE.match(text):
                    return {"error": "参数 %s 必须是 YYYY-MM-DD，收到 %r" % (key, value)}
            cleaned[key] = text
        for key in schema.get("required", []):
            if key not in cleaned:
                return {"error": "缺少必填参数 %s" % key}
        try:
            if name == "search_kb":
                return self.retrieve(cleaned["query"], cleaned.get("top_k", 5))
            # 所有工具输出都压到契约上限内，保证它作为 data_evidence 时不会超标。
            return fit_evidence(getattr(self.tools, name)(**cleaned))
        except (TypeError, ValueError, sqlite3.Error) as exc:
            return {"error": "工具 %s 执行失败：%s" % (name, exc)}

    # -- 问答 -------------------------------------------------------------------

    def chat(self, session_id: Optional[str], question: str) -> dict:
        trace = Trace(
            trace_id=self.traces.new_id(self.settings.today.isoformat()),
            question=question or "",
            session_id=session_id,
        )
        trace.mode = self.settings.llm_mode
        answer = self._answer(trace, session_id, question or "")
        # 采纳状态在**回答定稿之后**核对：只看最终要返回给调用方的 citations 与
        # data_evidence。工具执行成功、检索返回了候选片段，都不等于被采纳；
        # 回退成拒答时本轮所有工具结果都应当显示为未采纳。
        trace.reconcile(evidence=answer.data_evidence, citations=answer.citations)
        payload = {
            "answer": answer.answer,
            "answer_type": answer.answer_type,
            "citations": answer.citations,
            "data_evidence": answer.data_evidence,
            "trace_id": trace.trace_id,
        }
        # 回答本身的摘要也进 trace，面板才能一眼看到「最终给了什么」。
        trace.answer = {
            "type": answer.answer_type,
            "answer_preview": answer.answer[:600],
            "answer_length": len(answer.answer),
            "citations": [
                {"doc_id": item.get("doc_id"), "quote_preview": (item.get("quote") or "")[:200]}
                for item in answer.citations
            ],
            "evidence_count": len(answer.data_evidence),
            "notes": answer.notes,
        }
        trace.step("response", {"answer_type": answer.answer_type, "notes": answer.notes})
        # 落盘前统一脱敏：无论错误信息从哪条路径来，trace 里都不出现 Key。
        self.traces.save(trace, redactor=self._redact)
        return payload

    def _redact(self, payload):
        return _redact_payload(payload, self.settings.llm_api_key)

    def _answer(self, trace: Trace, session_id: Optional[str], question: str) -> Answer:
        try:
            if not question.strip():
                return Answer(answer="没有收到问题内容，请再说一次。", answer_type="clarify")
            history = self.sessions.history(session_id)
            started = time.perf_counter()
            # 把本会话的历史传给规划器，追问（“那 7 月呢”）才能补全。
            plan = self.planner.plan(question, history)
            trace.step("plan", plan.as_trace(), started=started)
            answer = self._run_engine(plan, trace, history)
            # 只有这一轮真的给出了可用结果，才把它写进会话上下文；
            # 反问、拒答不留下可供追问继承的槽位。
            if answer.answer_type not in ("clarify", "refusal"):
                self.sessions.append(
                    session_id,
                    {
                        "question": question,
                        "standalone": plan.standalone,
                        "slots": plan.slots,
                        "answer": answer.answer,
                        "answer_type": answer.answer_type,
                    },
                )
            return answer
        except Exception as exc:  # noqa: BLE001 - 不管里面出什么事，接口都得给个像样的回答
            trace.error("answer", exc)
            return Answer(
                answer="抱歉，我暂时无法回答。",
                answer_type="refusal",
                notes=["内部错误：%s" % exc],
            )

    def _run_engine(self, plan, trace: Trace, history: list[dict]) -> Answer:
        if not self.settings.live or plan.intent == "refusal":
            started = time.perf_counter()
            answer = self.answerer.answer(plan, trace)
            trace.step("answer_mock", {"answer_type": answer.answer_type}, started=started)
            return answer
        client = LLMClient(
            self.settings.llm_base_url,
            self.settings.llm_api_key,
            self.settings.llm_model,
            timeout=self.settings.llm_timeout,
        )
        engine = LiveEngine(
            client,
            self.answerer,
            self.run_tool,
            self.settings.today.isoformat(),
            self.data_period,
            budget=self.settings.chat_budget,
        )
        started = time.perf_counter()
        try:
            answer = engine.answer(plan, trace, history)
            trace.step("answer_live", {"answer_type": answer.answer_type}, started=started)
            return answer
        except LLMError as exc:
            # 异常信息本身可能回显 Key（如非法 JSON 的响应正文），这里再脱敏一遍。
            detail = redact_secret(exc.detail, self.settings.llm_api_key)
            trace.error("llm", exc)
            trace.step("answer_live_failed", {"kind": exc.kind, "detail": detail}, started=started)
            return Answer(
                answer="模型服务这次没有正常返回（%s），为了不给出没有依据的数字，这个问题先不回答。"
                "可以稍后重试；失败的真实原因记在 trace 里。" % _reason_cn(exc),
                answer_type="refusal",
                notes=["live 模式失败：%s" % detail],
            )

    # -- trace ------------------------------------------------------------------

    def get_trace(self, trace_id: str) -> Optional[dict]:
        return self.traces.get(trace_id)


def _redact_payload(value, secret: str):
    """递归脱敏：trace 里的任何字符串（提示词、原始响应、错误详情）都过一遍。"""
    if isinstance(value, str):
        return redact_secret(value, secret)
    if isinstance(value, dict):
        return {key: _redact_payload(item, secret) for key, item in value.items()}
    if isinstance(value, list):
        return [_redact_payload(item, secret) for item in value]
    return value


def _reason_cn(exc: LLMError) -> str:
    mapping = {
        "timeout": "调用超时",
        "http_error": "接口返回错误码 %s" % (exc.status or ""),
        "empty_content": "返回了空回答",
        "length": "输出额度被思考耗尽",
        "content_filter": "被内容过滤拦截",
        "insufficient_system_resource": "服务端资源不足",
        "aborted": "请求被中止",
        "bad_tool_args": "工具参数无法解析",
        "bad_json": "返回的不是合法 JSON",
        "budget": "整体耗时接近时限",
        "transport": "网络异常",
        "tool_loop": "工具调用没有收敛",
    }
    return mapping.get(exc.kind, exc.kind)
