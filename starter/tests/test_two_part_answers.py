"""混合问题（文档 + 数据夹在同一句里）的两半都要答上。

第三关要求“两样都要”的问题必须同时给出 `citations` 与 `data_evidence`。
`planner` 里的 `two_part` 曾经被写死成 `False`，`answerer._merge_doc_side` /
`_merge_data_side` 两条合并路径因此是死代码——一句话里夹带的另一半被静默丢掉。
这些用例先把那个缺口钉住：文档题必须带上数字，数据题必须带上依据。

检索用真实实现（`real_retriever`），否则引用无法逐字核对。
"""

from __future__ import annotations

import pytest


def _chat(client, question, session="tp"):
    resp = client.post("/api/chat", json={"session_id": session, "question": question})
    assert resp.status_code == 200
    return resp.json()


# -- 文档题里夹带一个能查的数字 ------------------------------------------------


def test_doc_question_with_embedded_number_answers_both_sides(real_retriever, client):
    body = _chat(client, "外卖订单多久内可以退款，7 月一共退了多少款？")
    assert body["answer_type"] == "hybrid"
    # 数据那一半：7 月退款金额必须来自真实查询
    assert body["data_evidence"], "夹带的数字也必须给出 data_evidence"
    tools = [item["tool"] for item in body["data_evidence"]]
    assert "query_metrics" in tools
    params = next(item["params"] for item in body["data_evidence"] if item["tool"] == "query_metrics")
    assert params["start"] == "2026-07-01" and params["end"] == "2026-07-31"
    # 文档那一半：时限仍然要引用到 KB-013
    doc_ids = [c["doc_id"] for c in body["citations"]]
    assert "KB-013" in doc_ids
    assert "24 小时" in body["answer"]


def test_doc_question_with_embedded_payment_mix_answers_both_sides(real_retriever, client):
    body = _chat(client, "会员充值的规定是什么，8 月储值支付占比多少？")
    assert body["answer_type"] == "hybrid"
    tools = [item["tool"] for item in body["data_evidence"]]
    assert "payment_mix" in tools, "问支付占比时要查 payment_mix，不能拿净营业额糊弄"
    doc_ids = [c["doc_id"] for c in body["citations"]]
    assert "KB-011" in doc_ids


# -- 数据题里夹带一个规定 -------------------------------------------------------


def test_data_question_with_embedded_policy_cites_the_rule(real_retriever, client):
    body = _chat(client, "7 月净营业额是多少，口径怎么算？")
    assert body["answer_type"] == "hybrid"
    assert body["data_evidence"], "数字那一半照旧要给证据"
    assert body["citations"], "口径那一半要引用到手册"
    assert any(c["doc_id"] == "KB-001" for c in body["citations"])


# -- 只有一半的问题不能被误判成两半 --------------------------------------------


@pytest.mark.parametrize(
    "question",
    [
        "外卖订单多久内可以申请退款？",
        "退款在净营业额里是怎么算的？",
        "会员现在单笔充值满 500 送多少？",
        "7 月顾客投诉最集中的是什么问题？有多少条？",
    ],
)
def test_single_sided_questions_do_not_gain_the_other_side(real_retriever, client, question):
    body = _chat(client, question)
    assert body["answer_type"] in ("doc", "clarify", "refusal")
    assert body["data_evidence"] == [], "纯文档问题不该顺手查一次库：%s" % question


def test_pure_data_question_does_not_gain_citations(real_retriever, client):
    body = _chat(client, "7 月整体的净营业额是多少？")
    assert body["answer_type"] == "data"
    assert body["citations"] == []
    assert body["data_evidence"]
