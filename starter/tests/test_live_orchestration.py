"""live 编排回归：search_kb 继承 Plan 检索约束；数据库工具参数与 Plan 一致性校验。

用桩件替掉模型与检索，不联网、不依赖真实知识库，直接验证 LiveEngine 的编排逻辑。
"""

from __future__ import annotations

import json
from datetime import date
from types import SimpleNamespace

from kbqa.live import LiveEngine
from kbqa.schemas import Answer
from kbqa.trace import Trace


class FakeFacts:
    def term_weights(self, query):
        return {}

    def cite(self, doc_id, quote):
        return None


class StubAnswerer:
    def __init__(self, retriever):
        self.facts = FakeFacts()
        self.retriever = retriever

    def answer(self, plan, trace=None):
        return Answer(answer="（兜底）", answer_type="refusal")


class RecordingRetriever:
    def __init__(self):
        self.calls = []

    def search(self, query, top_k=5, **kwargs):
        self.calls.append({"query": query, "top_k": top_k, **kwargs})
        from kbqa.retriever import SearchResult

        return SearchResult(hits=[], query=query, terms=[], expansions=[], filtered=[])


class FakeReply:
    def __init__(self, tool_calls=None, content=""):
        self.tool_calls = tool_calls or []
        self.content = content
        self.message = {"role": "assistant", "content": content}


class FakeClient:
    def __init__(self, replies):
        self._replies = list(replies)

    def chat_with_retry(self, messages, tools, budget=None, on_call=None):
        return self._replies.pop(0)


def _engine(retriever, client=None, run_tool=None):
    return LiveEngine(
        client=client,
        answerer=StubAnswerer(retriever),
        run_tool=run_tool,
        today="2026-09-01",
        data_period={"start": "2026-05-01", "end": "2026-08-31"},
    )


def _plan(**overrides):
    base = dict(
        question="q",
        standalone="q",
        search_query="q",
        as_of=date(2026, 6, 15),
        window=("2026-06-01", "2026-06-30"),
        compare_window=None,
        store_id="S02",
        product_id=None,
        year=None,
        needs_data=True,
        needs_docs=False,
        intent="hybrid",
        kind="summary",
        metric="net_revenue",
        refusal=None,
        notes=[],
        slots={"historical": True, "metric_explicit": True},
    )
    base.update(overrides)
    return SimpleNamespace(**base)


# -- search_kb 继承 Plan 检索约束 -----------------------------------------------


def test_search_kb_inherits_plan_constraints():
    retriever = RecordingRetriever()
    engine = _engine(retriever)
    plan = _plan()
    engine._search_kb({"query": "退款 时限", "top_k": 3}, plan, Trace("t", "q"), 0.0)

    call = retriever.calls[0]
    assert call["query"] == "退款 时限"
    assert call["top_k"] == 3
    assert call["as_of"] == date(2026, 6, 15)
    assert call["historical"] is True
    assert call["store_id"] == "S02"
    assert call["window"] == ("2026-06-01", "2026-06-30")
    assert call["numeric"] is True


def test_search_kb_uses_plan_as_of_when_model_does_not_guess():
    """历史日期由 Plan 决定，模型传不传都一样——不靠模型猜。"""
    retriever = RecordingRetriever()
    engine = _engine(retriever)
    plan = _plan(as_of=date(2026, 5, 20))
    engine._search_kb({"query": "当时的规定"}, plan, Trace("t", "q"), 0.0)
    assert retriever.calls[0]["as_of"] == date(2026, 5, 20)


# -- 数据库工具参数与 Plan 一致性 ----------------------------------------------


def test_scope_error_wrong_store_rejected():
    engine = _engine(RecordingRetriever())
    plan = _plan(store_id="S02")
    err = engine._scope_error(
        plan, "query_metrics", {"start": "2026-06-01", "end": "2026-06-30", "store_id": "S05"}
    )
    assert err and "S05" in err and "S02" in err


def test_scope_error_wrong_window_rejected():
    engine = _engine(RecordingRetriever())
    plan = _plan(window=("2026-06-01", "2026-06-30"))
    err = engine._scope_error(
        plan, "query_metrics", {"start": "2026-07-01", "end": "2026-07-31"}
    )
    assert err and "不一致" in err


def test_scope_error_correct_scope_ok():
    engine = _engine(RecordingRetriever())
    plan = _plan(window=("2026-06-01", "2026-06-30"), store_id="S02")
    assert (
        engine._scope_error(
            plan,
            "query_metrics",
            {"start": "2026-06-01", "end": "2026-06-30", "store_id": "S02"},
        )
        is None
    )


def test_scope_error_compare_window_allowed():
    engine = _engine(RecordingRetriever())
    plan = _plan(
        window=("2026-06-01", "2026-06-30"), compare_window=("2026-07-01", "2026-07-31")
    )
    ok = engine._scope_error(
        plan,
        "compare_periods",
        {"start_a": "2026-06-01", "end_a": "2026-06-30", "start_b": "2026-07-01", "end_b": "2026-07-31"},
    )
    assert ok is None
    bad = engine._scope_error(
        plan,
        "compare_periods",
        {"start_a": "2026-05-01", "end_a": "2026-05-31", "start_b": "2026-07-01", "end_b": "2026-07-31"},
    )
    assert bad is not None


# -- 端到端：查错范围的工具结果不得进入证据 -------------------------------------


def test_wrong_scope_tool_result_not_used_as_evidence():
    def run_tool(name, params):
        # 模型查了错误区间，却拿回来一个“真实”数字——不能当证据。
        return {"net_revenue": 9999999.0, "orders": 1}

    engine = _engine(
        RecordingRetriever(),
        client=FakeClient(
            [
                FakeReply(
                    tool_calls=[
                        {
                            "id": "c1",
                            "function": {
                                "name": "query_metrics",
                                "arguments": json.dumps(
                                    {"start": "2026-07-01", "end": "2026-07-31"}
                                ),
                            },
                        }
                    ]
                ),
                FakeReply(content="净营业额是9999999元。"),
            ]
        ),
        run_tool=run_tool,
    )
    plan = _plan(window=("2026-06-01", "2026-06-30"), intent="data", kind="summary",
                 slots={"metric_explicit": False})
    trace = Trace("t2", plan.question)
    answer = engine.answer(plan, trace, [])

    assert answer.data_evidence == []
    assert answer.answer == "（兜底）"
    # 被拒绝的工具调用要留下痕迹：status=rejected、accepted=False、带原因。
    rejected = [item for item in trace.tools if item["status"] == "rejected"]
    assert rejected, "查错区间的工具调用应记为 rejected"
    assert rejected[0]["accepted"] is False
    assert "不一致" in rejected[0]["reject_reason"]
