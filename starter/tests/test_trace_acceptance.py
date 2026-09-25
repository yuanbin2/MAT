"""trace 的采纳语义：检索执行成功、返回候选片段、最终形成引用，是三件不同的事。

守的是这条教训（DEBUG_LOG D31）：过去 search_kb 一执行完就写
`accepted=True, entered="citations"`，于是面板显示"已采纳/已引用"，
而回答里可能一个字都没引用——面板描述和实际返回对不上。

现在的规则：工具条目先记成"待定"，等回答定稿后由 `Trace.reconcile()` 按**最终返回的**
`citations` / `data_evidence` 回填。这里覆盖四种收尾：零命中后拒答、命中了但没引用、
命中且被引用、模型失败/回退。
"""

from __future__ import annotations

import json
from datetime import date
from types import SimpleNamespace



from kbqa.live import LiveEngine
from kbqa.schemas import Answer
from kbqa.trace import Trace

DOC_TEXT = "退款政策 v2。外卖订单在订单送达后 24 小时内可以申请退款。"


# -- 桩件 -------------------------------------------------------------------


class StubFacts:
    """只实现 LiveEngine 用到的三样：词权重、逐字核对、以及 index.docs_meta。"""

    def __init__(self):
        self.index = SimpleNamespace(docs_meta={})

    def term_weights(self, query):
        return {}

    def cite(self, doc_id, quote):
        quote = (quote or "").strip()
        return {"doc_id": doc_id, "quote": quote} if quote else None


class StubAnswerer:
    def __init__(self, retriever):
        self.facts = StubFacts()
        self.retriever = retriever
        self.fallback_calls = 0

    def answer(self, plan, trace=None):
        self.fallback_calls += 1
        return Answer(answer="（兜底：按工具结果模板回答）", answer_type="refusal")


class StubRetriever:
    def __init__(self, hits):
        self._hits = list(hits)
        self.calls = []

    def search(self, query, top_k=5, **kwargs):
        from kbqa.retriever import SearchResult

        self.calls.append({"query": query, **kwargs})
        return SearchResult(
            hits=list(self._hits)[:top_k], query=query, terms=[], expansions=[], filtered=[]
        )


def _hit(doc_id="KB-013", text=DOC_TEXT):
    from kbqa.retriever import Hit

    return Hit(
        doc_id=doc_id,
        chunk_id="%s#1" % doc_id,
        score=3.5,
        text=text,
        source_text=text,
        meta={"title": doc_id, "status": "现行"},
    )


class _Reply:
    def __init__(self, tool_calls=None, content=""):
        self.tool_calls = tool_calls or []
        self.content = content
        self.message = {"role": "assistant", "content": content}


def _tool_call(name, args, call_id="c1"):
    return [{"id": call_id, "function": {"name": name, "arguments": json.dumps(args)}}]


class ScriptedClient:
    def __init__(self, replies):
        self._replies = list(replies)

    def chat_with_retry(self, messages, tools, budget=None, on_call=None):
        reply = self._replies.pop(0)
        if isinstance(reply, BaseException):
            raise reply
        return reply


def _engine(retriever, replies, run_tool=None):
    answerer = StubAnswerer(retriever)
    engine = LiveEngine(
        client=ScriptedClient(replies),
        answerer=answerer,
        run_tool=run_tool,
        today="2026-09-01",
        data_period={"start": "2026-05-01", "end": "2026-08-31"},
    )
    return engine, answerer


def _plan(**overrides):
    base = dict(
        question="外卖订单多久内可以申请退款？",
        standalone="外卖订单多久内可以申请退款？",
        search_query="外卖订单 退款 时限",
        as_of=date(2026, 9, 1),
        window=("2026-06-01", "2026-06-30"),
        compare_window=None,
        store_id=None,
        product_id=None,
        year=None,
        needs_data=False,
        needs_docs=True,
        intent="doc",
        kind="doc",
        metric=None,
        refusal=None,
        notes=[],
        slots={},
    )
    base.update(overrides)
    return SimpleNamespace(**base)


def _search_entry(trace):
    entries = [item for item in trace.tools if item["tool"] == "search_kb"]
    assert entries, "应当记录到一次 search_kb"
    return entries[0]


# -- 四种收尾 ---------------------------------------------------------------


def test_zero_hits_after_refusal_is_not_accepted():
    """零命中 → 拒答；检索条目必须是"未采纳 + 没命中"，不能是已引用。"""
    engine, _ = _engine(StubRetriever([]), [
        _Reply(tool_calls=_tool_call("search_kb", {"query": "外卖订单 退款 时限"})),
        _Reply(content="现有资料里没有相关说明，无法确定。"),
    ])
    plan = _plan()
    trace = Trace("t-zero", plan.question)

    answer = engine.answer(plan, trace, [])
    trace.reconcile(evidence=answer.data_evidence, citations=answer.citations)

    assert answer.answer_type == "refusal"
    assert answer.citations == []
    entry = _search_entry(trace)
    assert entry["status"] == "ok", "检索本身是执行成功的（这跟被采纳是两回事）"
    assert entry["accepted"] is False
    assert "pending" not in entry, "定稿后不应再留待定"
    assert "entered" not in entry
    assert "没有命中" in entry["reject_reason"]


def test_hits_without_citation_is_not_accepted():
    """命中了候选片段，但回答没有引用它 → 仍是未采纳，原因说清楚。"""
    engine, _ = _engine(StubRetriever([_hit()]), [
        _Reply(tool_calls=_tool_call("search_kb", {"query": "外卖订单 退款 时限"})),
        _Reply(content="这个问题知识库里没有明确写到。"),
    ])
    plan = _plan()
    trace = Trace("t-uncited", plan.question)

    answer = engine.answer(plan, trace, [])
    trace.reconcile(evidence=answer.data_evidence, citations=answer.citations)

    assert answer.citations == []
    entry = _search_entry(trace)
    assert entry["accepted"] is False
    assert "没有引用" in entry["reject_reason"]


def test_hits_with_citation_is_accepted_into_citations():
    """命中且最终形成引用 → 才算 accepted，并标明进了 citations。"""
    engine, _ = _engine(StubRetriever([_hit()]), [
        _Reply(tool_calls=_tool_call("search_kb", {"query": "外卖订单 退款 时限"})),
        _Reply(content="外卖订单在送达后 24 小时内可以申请退款。 [KB-013]"),
    ])
    plan = _plan()
    trace = Trace("t-cited", plan.question)

    answer = engine.answer(plan, trace, [])
    trace.reconcile(evidence=answer.data_evidence, citations=answer.citations)

    assert [item["doc_id"] for item in answer.citations] == ["KB-013"]
    entry = _search_entry(trace)
    assert entry["accepted"] is True
    assert entry["entered"] == "citations"
    assert "reject_reason" not in entry


def test_pending_is_not_claimed_accepted_before_reconcile():
    """定稿前不能声称已采纳——这正是回归前的 bug。"""
    engine, _ = _engine(StubRetriever([_hit()]), [
        _Reply(tool_calls=_tool_call("search_kb", {"query": "外卖订单 退款 时限"})),
        _Reply(content="外卖订单在送达后 24 小时内可以申请退款。 [KB-013]"),
    ])
    plan = _plan()
    trace = Trace("t-pending", plan.question)
    engine.answer(plan, trace, [])

    # 还没 reconcile：条目必须停在"待定 + 未采纳"
    entry = _search_entry(trace)
    assert entry["accepted"] is False
    assert entry["pending"] is True
    assert "entered" not in entry


# -- 数据库工具：查到数字 ≠ 进了最终回答 ------------------------------------


def _metrics_tool(name, params):
    return {"start": params["start"], "end": params["end"], "net_revenue": 12345.0, "orders": 100}


def test_data_tool_accepted_only_when_in_final_evidence():
    engine, _ = _engine(
        StubRetriever([]),
        [
            _Reply(tool_calls=_tool_call("query_metrics", {"start": "2026-06-01", "end": "2026-06-30"})),
            _Reply(content="六月净营业额 12345 元。"),
        ],
        run_tool=_metrics_tool,
    )
    plan = _plan(needs_data=True, intent="data", kind="summary", metric="net_revenue")
    trace = Trace("t-data", plan.question)

    answer = engine.answer(plan, trace, [])
    trace.reconcile(evidence=answer.data_evidence, citations=answer.citations)

    assert answer.answer_type == "data"
    entry = trace.tools[0]
    assert entry["tool"] == "query_metrics"
    assert entry["accepted"] is True
    assert entry["entered"] == "data_evidence"


def test_data_tool_not_accepted_when_answer_falls_back():
    """模型回答里的数字没有依据 → 回退成模板答案；此时那个查询结果并没有被采用。"""
    engine, answerer = _engine(
        StubRetriever([]),
        [
            _Reply(tool_calls=_tool_call("query_metrics", {"start": "2026-06-01", "end": "2026-06-30"})),
            _Reply(content="六月净营业额 9999999 元。"),  # 与查询结果对不上
        ],
        run_tool=_metrics_tool,
    )
    plan = _plan(needs_data=True, intent="data", kind="summary", metric="net_revenue")
    trace = Trace("t-fallback", plan.question)

    answer = engine.answer(plan, trace, [])
    trace.reconcile(evidence=answer.data_evidence, citations=answer.citations)

    assert answerer.fallback_calls == 1, "应当发生了回退"
    assert answer.answer_type == "refusal"
    assert answer.data_evidence == []
    entry = trace.tools[0]
    assert entry["accepted"] is False
    assert "没有进入最终回答依据" in entry["reject_reason"]


def test_private_fields_never_leak_into_trace_payload():
    engine, _ = _engine(StubRetriever([_hit()]), [
        _Reply(tool_calls=_tool_call("search_kb", {"query": "外卖订单 退款 时限"})),
        _Reply(content="外卖订单在送达后 24 小时内可以申请退款。 [KB-013]"),
    ])
    plan = _plan()
    trace = Trace("t-priv", plan.question)
    answer = engine.answer(plan, trace, [])
    trace.reconcile(evidence=answer.data_evidence, citations=answer.citations)

    dump = json.dumps(trace.as_dict(), ensure_ascii=False)
    assert "_evidence_obj" not in dump
    assert "_doc_ids" not in dump
    assert "KB-013" in dump, "该留的证据还是要留"


# -- 服务级：模型失败 -------------------------------------------------------


def test_service_marks_all_tools_unaccepted_when_model_fails(monkeypatch):
    """模型调用失败 → 返回结构化拒答；本轮检索到的候选也不得显示成"已引用"。"""
    from dataclasses import replace

    import kbqa.service as service_module
    from kbqa.config import load_settings
    from kbqa.llm import LLMError
    from kbqa.service import Service

    class BoomClient:
        def __init__(self, *args, **kwargs):
            self._replies = [
                _Reply(tool_calls=_tool_call("search_kb", {"query": "退款 时限", "top_k": 5})),
                LLMError("timeout", "等待模型响应超时"),
            ]

        def chat_with_retry(self, messages, tools, budget=None, on_call=None):
            reply = self._replies.pop(0)
            if isinstance(reply, BaseException):
                raise reply
            return reply

    monkeypatch.setattr(service_module, "LLMClient", BoomClient)

    settings = replace(
        load_settings(),
        llm_base_url="https://api.example.test/v1",
        llm_api_key="sk-fake-for-test",
        llm_model="fake-model",
    )
    service = Service(settings)
    out = service.chat("s-fail", "外卖订单多久内可以申请退款？")
    trace = service.get_trace(out["trace_id"])

    assert out["answer_type"] == "refusal"
    assert out["citations"] == []
    search_entries = [item for item in trace["tools"] if item["tool"] == "search_kb"]
    assert search_entries, "检索确实执行过（只是没被采用）"
    entry = search_entries[0]
    assert entry["status"] == "ok"
    assert entry["accepted"] is False
    assert "pending" not in entry, "失败路径也要把待定状态收尾"
    assert entry.get("reject_reason"), "要给面板一个能解释得通的原因"
    assert trace["errors"], "模型失败本身要留在 trace 里"


def test_reconcile_reason_distinguishes_zero_hits_from_uncited():
    """同样一次"检索成功"，零命中与"命中但没引用"必须给出不同的解释。"""
    empty = Trace("t-empty", "q")
    empty_entry = empty.tool(
        tool="search_kb", params={"query": "x"}, status="ok", pending=True, retrieved_doc_ids=[]
    )
    empty.reconcile(evidence=[], citations=[])
    assert empty_entry["accepted"] is False
    assert "没有命中" in empty_entry["reject_reason"]

    hit = Trace("t-hit", "q")
    hit_entry = hit.tool(
        tool="search_kb",
        params={"query": "x"},
        status="ok",
        pending=True,
        retrieved_doc_ids=["KB-013"],
    )
    hit.reconcile(evidence=[], citations=[])
    assert hit_entry["accepted"] is False
    assert "没有引用" in hit_entry["reject_reason"]

    # 同一个条目，若最终真的引用了它，结论要翻过来
    cited = Trace("t-cited-only", "q")
    cited_entry = cited.tool(
        tool="search_kb",
        params={"query": "x"},
        status="ok",
        pending=True,
        retrieved_doc_ids=["KB-013"],
    )
    cited.reconcile(evidence=[], citations=[{"doc_id": "KB-013", "quote": "x"}])
    assert cited_entry["accepted"] is True
    assert cited_entry["entered"] == "citations"
    assert "reject_reason" not in cited_entry
