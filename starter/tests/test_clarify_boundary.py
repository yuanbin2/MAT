"""D44 回归：规划器的确定性判定对 live 模式也是硬约束。

两个缺口，2026-10-08 实测复现（trace t-20260901-1300）：
1. 短追问句式的问句（「今天天气怎么样」，7 字、命中追问句式）若问的是"无从知道"的事
   （天气/预测/外部价格/薪酬），应判 out_of_scope 如实拒答，而不是反问"请补全"；
2. live 模式下 service 只把 intent == "refusal" 留在本地，clarify 被放行给模型——
   实测模型自由作答并引用不相干文档（KB-042 极端天气），违背"如实拒答"的契约要求。

测试用打桩 scout（覆盖率 0、最高分 0）保证确定性，不依赖知识库内容。
"""

from __future__ import annotations

from dataclasses import replace

import kbqa.service as service_module
from kbqa.config import load_settings
from kbqa.service import Service


def make_service(monkeypatch, **live_kw):
    base = load_settings()
    settings = replace(base, **live_kw) if live_kw else base
    service = Service(settings)
    # 打桩 scout：语料没讲这件事（覆盖率 0、检索最高分 0），确定性不随知识库换数据而变。
    monkeypatch.setattr(service.planner, "scout", lambda head: (0.0, 0.0))
    return service


def test_short_weather_question_refuses_out_of_scope(monkeypatch):
    """「今天天气怎么样」≤12 字且像追问，但主句是天气——应 out_of_scope 拒答，不能 clarify。"""
    service = make_service(monkeypatch)
    plan = service.planner.plan("今天天气怎么样", [])
    assert plan.intent == "refusal", "问天气这类无从知道的事必须拒答，实测却判成了 clarify"
    assert plan.kind == "out_of_scope"
    assert plan.refusal, "拒答原因必须写在 plan.refusal 里"


def test_short_ambiguous_followup_still_clarifies(monkeypatch):
    """不含"无从知道"话题的短问句仍是 clarify——X07（10 号那天卖了多少，need_month）的行为不能变。"""
    service = make_service(monkeypatch)
    plan = service.planner.plan("10 号那天卖了多少？", [])
    assert plan.intent == "clarify"
    assert plan.kind == "need_month"


def test_live_mode_must_not_send_clarify_plan_to_model(monkeypatch):
    """live 模式下 clarify 也必须走本地渲染——不能把规划器的判定交给模型自由发挥。"""
    settings = replace(
        load_settings(),
        llm_base_url="https://fake.example/v1",
        llm_api_key="sk-test-not-real",
        llm_model="fake-model",
    )
    service = Service(settings)
    monkeypatch.setattr(service.planner, "scout", lambda head: (0.0, 0.0))

    class MustNotRun:
        def __init__(self, *args, **kwargs):
            raise AssertionError("clarify 计划不应该被交给 live 引擎")

        def answer(self, *args, **kwargs):  # pragma: no cover
            raise AssertionError("clarify 计划不应该被交给 live 引擎")

    monkeypatch.setattr(service_module, "LiveEngine", MustNotRun)
    out = service.chat("sess-d44", "10 号那天卖了多少？")
    assert out["answer_type"] == "clarify", (
        "live 模式下 clarify 必须由本地渲染，实测被交给了模型（修复前此处为 refusal 兜底）"
    )
