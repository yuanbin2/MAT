"""D45 回归：排名类问题没说"比什么"时，反问指标而不是瞎猜或拒答；拒答文案给出"可以怎么问"。

2026-10-08 实测：live 下问「哪个店铺最好」，规划器没识别成数据题（"最好"不带销量词、
没点指标 → may_query=False），掉进文档检索 → 检索不到 → 冷拒答。对运营来说更好的行为是
反问"你想按哪个方面比较"——宁可澄清，不猜指标。
"""

from __future__ import annotations

from kbqa.config import load_settings
from kbqa.service import Service


def make_service(monkeypatch):
    service = Service(load_settings())
    # 打桩 scout：语料没讲这件事，out_of_scope 判定确定性地不放大放行。
    monkeypatch.setattr(service.planner, "scout", lambda head: (0.0, 0.0))
    return service


def test_store_rank_without_metric_clarifies(monkeypatch):
    """「哪个店铺最好」没说比什么 → 反问指标（净营业额/订单数/销量/客单价），不能冷拒答。"""
    service = make_service(monkeypatch)
    plan = service.planner.plan("哪个店铺最好", [])
    assert plan.intent == "clarify", "无指标的门店排名应反问，实测掉进了文档拒答"
    assert plan.kind == "need_metric"
    for word in ("净营业额", "销量", "订单"):
        assert word in (plan.refusal or ""), "反问里要给出可选方面，引导用户补全"


def test_product_rank_without_metric_clarifies(monkeypatch):
    """「哪个商品最好」同理反问。"""
    service = make_service(monkeypatch)
    plan = service.planner.plan("哪个商品最好", [])
    assert plan.intent == "clarify"
    assert plan.kind == "need_metric"
    assert "销量" in (plan.refusal or "")


def test_store_rank_with_metric_not_clarify(monkeypatch):
    """说了指标的排名不能被反问挡住：「销量最高的门店」仍应走数据题。"""
    service = make_service(monkeypatch)
    plan = service.planner.plan("销量最高的门店是哪家", [])
    assert plan.intent == "data", "带销量词的门店排名是数据题，不能被反问拦截"
    assert plan.kind == "by_store"


def test_doc_miss_refusal_gives_guidance(monkeypatch):
    """检索不到的冷拒答要给出"可以问什么"的引导，不能只说"我不能编"。

    打桩空检索确定性复现"零命中"路径，不依赖真实知识库的弱命中。
    """
    service = make_service(monkeypatch)

    from kbqa.retriever import SearchResult

    def zero_search(self, query, top_k=5, **kwargs):
        return SearchResult(hits=[], query=query, terms=[], expansions=[], filtered=[], coverage=0.0)

    monkeypatch.setattr(type(service.retriever), "search", zero_search)
    out = service.chat("sess-d45", "附近有什么电影院")
    assert out["answer_type"] == "refusal"
    assert "经营数字" in out["answer"], "拒答里应引导用户：系统能查经营数字"
    assert "制度" in out["answer"], "拒答里应引导用户：系统能查公司制度"
