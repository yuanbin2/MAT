"""live 编排的收口行为：最后一轮撤掉工具，强制模型用已有证据作答。

守的是这条实测发现的缺陷（DEBUG_LOG D34）：plan 类模型（StepFun step-5-preview）会
换着关键词一轮轮检索，**拿够了证据也不收口**，把 4 轮工具预算耗光，
最后整道题变成一个"工具调用没有收敛"的拒答——而它检索到的文档其实是对的。
"""

from __future__ import annotations

import json
from datetime import date
from types import SimpleNamespace

from kbqa.live import MAX_TOOL_ROUNDS, LiveEngine
from kbqa.schemas import Answer
from kbqa.trace import Trace


class StubFacts:
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
        return Answer(answer="（兜底）", answer_type="refusal")


class StubRetriever:
    def search(self, query, top_k=5, **kwargs):
        from kbqa.retriever import Hit, SearchResult

        text = "供应商邮件：Tasman Cold Chain 就该批次三文鱼拒收出具了信用单据。"
        hit = Hit(
            doc_id="KB-022",
            chunk_id="KB-022#1",
            score=4.0,
            text=text,
            source_text=text,
            meta={"title": "KB-022"},
        )
        return SearchResult(hits=[hit], query=query, terms=[], expansions=[], filtered=[])


class _Reply:
    def __init__(self, tool_calls=None, content=""):
        self.tool_calls = tool_calls or []
        self.content = content
        self.message = {"role": "assistant", "content": content}


def _search_call(call_id="c"):
    return [
        {
            "id": call_id,
            "function": {"name": "search_kb", "arguments": json.dumps({"query": "三文鱼 赔偿"})},
        }
    ]


class RecordingClient:
    """记下每次调用时**有没有给工具**——这正是本轮要验证的行为。"""

    def __init__(self, replies):
        self._replies = list(replies)
        self.tool_args: list[bool] = []
        self.saw_messages: list[list[dict]] = []

    def chat_with_retry(self, messages, tools, budget=None, on_call=None):
        self.tool_args.append(bool(tools))
        self.saw_messages.append(list(messages))
        return self._replies.pop(0)


def _engine(retriever, client):
    return LiveEngine(
        client=client,
        answerer=StubAnswerer(retriever),
        run_tool=None,
        today="2026-09-01",
        data_period={"start": "2026-05-01", "end": "2026-08-31"},
    )


def _plan():
    return SimpleNamespace(
        question="三文鱼那次断供，供应商最后赔了我们多少钱？",
        standalone="三文鱼那次断供，供应商最后赔了我们多少钱？",
        search_query="三文鱼 供应商 赔偿",
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


def test_final_round_withholds_tools_and_answers():
    """模型一直检索不收口 → 最后一轮撤掉工具，它必须给出答案，而不是丢成拒答。"""
    # 前 MAX_TOOL_ROUNDS 轮都在检索，最后一轮（没有工具可用）才给出回答
    replies = [_Reply(tool_calls=_search_call("c%d" % i)) for i in range(MAX_TOOL_ROUNDS)]
    replies.append(_Reply(content="供应商就该批次出具了信用单据，具体金额需以单据为准。 [KB-022]"))
    client = RecordingClient(replies)
    engine = _engine(StubRetriever(), client)
    plan = _plan()
    trace = Trace("t-final", plan.question)

    answer = engine.answer(plan, trace, [])
    trace.reconcile(evidence=answer.data_evidence, citations=answer.citations)

    assert answer.answer_type != "refusal", answer.answer
    assert "信用单据" in answer.answer
    # 最后一轮没有给工具，前面几轮都给了
    assert client.tool_args[-1] is False
    assert all(client.tool_args[:-1]), client.tool_args
    assert len(client.tool_args) == MAX_TOOL_ROUNDS + 1
    # trace 里要能看出"这一轮是撤了工具的"
    assert any(step["step"] == "final_round_tools_withheld" for step in trace.steps)
    # 检索到的片段最终真的被引用，采纳状态也应当对得上
    assert [item["doc_id"] for item in answer.citations] == ["KB-022"]
    searches = [item for item in trace.tools if item["tool"] == "search_kb"]
    assert searches and searches[0]["accepted"] is True


def test_final_round_nudges_the_model_to_answer():
    """撤工具的同时要给一句话提醒，否则模型容易回一句"我再查一下"。"""
    replies = [_Reply(tool_calls=_search_call("c%d" % i)) for i in range(MAX_TOOL_ROUNDS)]
    replies.append(_Reply(content="无法从现有资料确定金额。"))
    client = RecordingClient(replies)
    engine = _engine(StubRetriever(), client)
    plan = _plan()

    engine.answer(plan, Trace("t-nudge", plan.question), [])

    last_messages = client.saw_messages[-1]
    last_user = [m for m in last_messages if m.get("role") == "user"][-1]
    assert "不要再检索" in last_user["content"]


def test_tool_loop_still_guards_against_a_model_that_ignores_the_withholding():
    """万一模型在没有工具的情况下还硬要调工具，仍然要有兜底，不能无限循环。"""
    import pytest

    from kbqa.llm import LLMError

    replies = [_Reply(tool_calls=_search_call("c%d" % i)) for i in range(MAX_TOOL_ROUNDS + 1)]
    client = RecordingClient(replies)
    engine = _engine(StubRetriever(), client)
    plan = _plan()

    with pytest.raises(LLMError) as excinfo:
        engine.answer(plan, Trace("t-loop", plan.question), [])
    assert excinfo.value.kind == "tool_loop"
