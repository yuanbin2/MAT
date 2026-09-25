"""检索的两处针对性修复（都是 live 全量评测里实测丢分后查 trace 找出来的）。

D38 切块把一句话切开，答案所在的兄弟片段进不了 top-k
    「冷萃乌龙茶上市第一个月的销量达标了吗」：匹配到商品名的是 KB-028 第 1 块，
    而"首月目标 900 杯"在第 3 块——`MAX_CHUNKS_PER_DOC = 1` 时第 3 块连候选都排不进，
    模型只能答"知识库里没有查到目标数值"。
    「供应商后来赔了多少」：`CNY 8,600` 在 KB-022 第 6 块，模型拿到的是第 1 块和第 7 块，
    中间断开，同样答"没有找到具体金额"。

D39 规划要文档依据，模型却一次都没检索
    多轮追问「那停售期间让顾客换成什么？」——模型凭上一轮上下文直接作答，
    既没有引用（`cite_all` 直接失败），还编出了一个知识库里没有的替代品。
"""

from __future__ import annotations

import json
from datetime import date
from types import SimpleNamespace

from kbqa.live import LiveEngine
from kbqa.trace import Trace


# -- D38：相邻片段扩展 --------------------------------------------------------


def _real_retriever():
    from kbqa.config import load_settings
    from kbqa.index import BM25Index
    from kbqa.retriever import Retriever

    settings = load_settings()
    payload = json.loads(settings.index_path.read_text(encoding="utf-8"))
    return Retriever(BM25Index.from_json(payload), date(2026, 9, 1))


def test_qa_path_reaches_the_chunk_that_holds_the_answer(real_retriever):
    """开扩展后，两道实测丢分题的目标片段必须出现在给模型的结果里。"""
    retriever = _real_retriever()

    h03 = retriever.search(
        "冷萃乌龙茶 上市 销量目标",
        top_k=10,
        as_of=date(2026, 9, 1),
        year=2026,
        window=("2026-05-01", "2026-08-31"),
        expand=True,
    )
    # KB-028#3 = “首月…全门店合计目标销量 900 杯。”
    assert "KB-028#3" in [hit.chunk_id for hit in h03.hits]

    t02 = retriever.search(
        "Tasman Cold Chain 三文鱼不合格 处理结果 赔偿金额 赔付 邮件正文",
        top_k=10,
        as_of=date(2026, 7, 31),
        year=2026,
        window=("2026-07-01", "2026-07-31"),
        expand=True,
    )
    # KB-022#6 = “…issue a credit note of CNY 8,600…”
    assert "KB-022#6" in [hit.chunk_id for hit in t02.hits]


def test_expansion_is_marked_and_capped(real_retriever):
    """补进来的片段要能看出来是补的，而且不能无上限地塞。"""
    from kbqa.retriever import EXPAND_MAX_EXTRA

    retriever = _real_retriever()
    result = retriever.search("冷萃乌龙茶 上市 销量目标", top_k=10, expand=True)

    added = [hit for hit in result.hits if hit.sibling]
    assert added, "开了扩展却没有补进任何相邻片段"
    assert len(added) <= EXPAND_MAX_EXTRA
    assert len(result.hits) <= 10 + EXPAND_MAX_EXTRA
    # 基础命中不能是 sibling
    assert len([hit for hit in result.hits if not hit.sibling]) >= 1


def test_retrieve_contract_still_returns_exactly_top_k(real_retriever):
    """`/api/retrieve` 不开扩展：契约 §4 要求索引够的时候恰好 top_k 条。"""
    retriever = _real_retriever()
    result = retriever.search("外卖订单多久内可以申请退款", top_k=5)

    assert len(result.hits) == 5
    assert not any(hit.sibling for hit in result.hits)


def test_retrieve_keeps_one_slot_per_doc(real_retriever):
    """检索接口必须保住"文档多样性"——放开一格会把 gold 文档挤出 top-5。

    实测教训：自拟题 X04「Super Souper 晚上几点关门」，gold 是 KB-062；
    每篇放开到两格后，top-5 里出现 KB-030 的两块，KB-062 反而没了。
    """
    retriever = _real_retriever()
    result = retriever.search("Super Souper 晚上几点关门", top_k=5)

    doc_ids = [hit.doc_id for hit in result.hits]
    assert len(doc_ids) == len(set(doc_ids)), doc_ids
    assert "KB-062" in doc_ids, doc_ids


def test_expansion_never_invents_chunks(real_retriever):
    """补的片段必须是真实存在的相邻块，不是拼出来的。"""
    retriever = _real_retriever()
    result = retriever.search("冷萃乌龙茶 上市 销量目标", top_k=10, expand=True)

    known = {chunk.chunk_id for chunk in retriever.index.chunks}
    assert all(hit.chunk_id in known for hit in result.hits)
    # 同一块不能出现两次
    ids = [hit.chunk_id for hit in result.hits]
    assert len(ids) == len(set(ids))


# -- D39：规划要文档依据但模型没检索 -------------------------------------------


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
        from kbqa.schemas import Answer

        return Answer(answer="（兜底）", answer_type="refusal")


class StubRetriever:
    def search(self, query, top_k=5, **kwargs):
        from kbqa.retriever import Hit, SearchResult

        text = "KB-021：停售期间向顾客推荐替代品鸡肉poke，米饭与配菜做法不变。"
        hit = Hit(
            doc_id="KB-021",
            chunk_id="KB-021#1",
            score=4.0,
            text=text,
            source_text=text,
            meta={"title": "KB-021"},
        )
        return SearchResult(hits=[hit], query=query, terms=[], expansions=[], filtered=[])


class _Reply:
    def __init__(self, tool_calls=None, content=""):
        self.tool_calls = tool_calls or []
        self.content = content
        self.message = {"role": "assistant", "content": content}


class RecordingClient:
    def __init__(self, replies):
        self._replies = list(replies)
        self.rounds = 0
        self.last_messages: list[dict] = []

    def chat_with_retry(self, messages, tools, budget=None, on_call=None):
        self.rounds += 1
        self.last_messages = list(messages)
        return self._replies.pop(0)


def _engine(client):
    return LiveEngine(
        client=client,
        answerer=StubAnswerer(StubRetriever()),
        run_tool=None,
        today="2026-09-01",
        data_period={"start": "2026-05-01", "end": "2026-08-31"},
    )


def _plan(**overrides):
    base = dict(
        question="那停售期间让顾客换成什么？",
        standalone="三文鱼poke 七月初为什么停售了？ 那停售期间让顾客换成什么？",
        search_query="三文鱼poke 停售 替代品",
        as_of=date(2026, 7, 31),
        window=("2026-07-01", "2026-07-31"),
        compare_window=None,
        store_id=None,
        product_id=None,
        year=2026,
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


def test_forced_retrieval_when_model_skips_searching():
    """模型没检索就要作答 → 先替它检一次，答案要带上引用。"""
    replies = [
        _Reply(content="建议换购金枪鱼poke碗。"),
        _Reply(content="停售期间推荐替代品鸡肉poke，米饭与配菜做法不变。 [KB-021]"),
    ]
    client = RecordingClient(replies)
    trace = Trace("t-forced", "那停售期间让顾客换成什么？")

    answer = _engine(client).answer(_plan(), trace, [])

    assert client.rounds == 2, "应当多给一轮，让它看着检索结果重答"
    assert "forced_retrieval" in [step["step"] for step in trace.steps]
    assert [c["doc_id"] for c in answer.citations] == ["KB-021"], answer.citations
    assert "鸡肉poke" in answer.answer


def test_forced_retrieval_happens_only_once():
    """补一次就够了；模型还是不引用也不能无限循环。"""
    replies = [
        _Reply(content="第一次没检索。"),
        _Reply(content="第二次还是没引用。"),
        _Reply(content="第三次。"),
    ]
    client = RecordingClient(replies)
    trace = Trace("t-once", "q")

    _engine(client).answer(_plan(), trace, [])

    forced = [step for step in trace.steps if step["step"] == "forced_retrieval"]
    assert len(forced) == 1, forced


def test_no_forced_retrieval_when_plan_needs_no_docs():
    """规划没要文档依据（纯数据题）时不该多此一举。"""
    client = RecordingClient([_Reply(content="净营业额 162414.00 元。")])
    trace = Trace("t-nodocs", "q")

    _engine(client).answer(_plan(needs_docs=False), trace, [])

    assert client.rounds == 1
    assert "forced_retrieval" not in [step["step"] for step in trace.steps]
