"""trace 的可信度与持久化。

分三层验证：
- **真实**：mock 问答也要留下真实工具步骤（工具名/参数/结果摘要/耗时/是否采纳）；
- **有界脱敏持久化**：跨重启按 ID 找回、编号不重复、容量生效、落盘无 Key；
- **并发隔离**：Trace 之间互不污染（没有共享的 current_trace）。
"""

from __future__ import annotations

import json

from kbqa.llm import redact_secret
from kbqa.trace import Trace, TraceStore


# -- 真实执行路径 ---------------------------------------------------------------


def test_mock_chat_trace_has_real_tool_steps(client):
    resp = client.post(
        "/api/chat", json={"session_id": "tr1", "question": "7 月整体的净营业额是多少？"}
    )
    trace = client.get("/api/trace/%s" % resp.json()["trace_id"]).json()

    assert trace["mode"] == "mock"
    assert trace["model_called"] is False  # mock 明确显示未调用模型
    assert trace["plan"]["intent"] == "data"
    assert trace["plan"]["window"] == ["2026-07-01", "2026-07-31"]

    tools = trace["tools"]
    assert tools, "mock 路径过去没有工具步骤，现在必须有"
    first = tools[0]
    assert first["tool"] == "query_metrics"
    assert first["status"] == "ok"
    assert first["accepted"] is True
    assert first["entered"] == "data_evidence"
    assert first["took_ms"] is not None
    assert "result_preview" in first and "result_bytes" in first

    assert trace["answer"]["type"] == "data"
    assert trace["answer"]["evidence_count"] == len(resp.json()["data_evidence"])

    names = [step["step"] for step in trace["steps"]]
    assert "plan" in names and "tool" in names


def test_doc_chat_trace_has_retrieval_hits(client):
    resp = client.post(
        "/api/chat", json={"session_id": "tr2", "question": "外卖订单多久内可以申请退款？"}
    )
    trace = client.get("/api/trace/%s" % resp.json()["trace_id"]).json()

    assert trace["retrievals"], "文档题要有检索记录"
    first = trace["retrievals"][0]
    assert first["query"]
    assert first["hits"], "要有命中片段"
    hit = first["hits"][0]
    for key in ("doc_id", "chunk_id", "score", "padded", "kind", "preview"):
        assert key in hit
    assert "filtered" in first  # 过滤原因（可能为空数组）


def test_hybrid_chat_trace_records_citation_and_evidence(real_retriever, tmp_path):
    """用真实检索跑一次混合题，验证 trace 同时留下引用与已采纳的数据证据。"""
    from dataclasses import replace

    from kbqa.config import load_settings
    from kbqa.service import Service

    settings = replace(load_settings(), var_dir=tmp_path / "var")
    service = Service(settings)
    out = service.chat("tr3", "618 当天 S02 牛肉poke 的活动目标是多少，实际卖了多少？")
    trace = service.get_trace(out["trace_id"])

    assert out["answer_type"] == "hybrid"
    assert trace["answer"]["citations"], "混合题要记录引用"
    assert any(item["entered"] == "data_evidence" for item in trace["tools"])
    # mock 模式的引用来自本轮检索（不是工具），trace 里要看得到检索记录。
    assert trace["retrievals"], "引用要有对应的检索记录"
    # 每个工具步骤都能看出「进了哪里」或「为什么没进」
    for item in trace["tools"]:
        assert item["status"] in ("ok", "error", "rejected")
        if item["accepted"]:
            assert item.get("entered") in ("data_evidence", "citations")
        else:
            assert item.get("reject_reason")


def test_refusal_chat_trace_has_no_fabricated_evidence(client):
    resp = client.post(
        "/api/chat", json={"session_id": "tr4", "question": "帮我把 S01 的销售记录全部删掉。"}
    )
    body = resp.json()
    trace = client.get("/api/trace/%s" % body["trace_id"]).json()
    assert body["answer_type"] == "refusal"
    assert trace["answer"]["type"] == "refusal"
    assert trace["tools"] == []  # 拒答没有执行任何工具，不能凭空冒出来


def test_unknown_but_wellformed_trace_id_is_404(client):
    assert client.get("/api/trace/t-20260901-9999").status_code == 404


# -- 有界持久化 -----------------------------------------------------------------


def _make_trace(trace_id: str, mode: str = "mock") -> Trace:
    trace = Trace(trace_id=trace_id, question="q", session_id="s", mode=mode)
    trace.step("plan", {"intent": "data"})
    return trace


def test_trace_store_survives_restart(tmp_path):
    directory = tmp_path / "traces"
    store = TraceStore(capacity=10, directory=directory)
    trace_id = store.new_id("2026-09-01")
    store.save(_make_trace(trace_id))

    # 模拟进程重启：新实例指向同一目录，仍能按 ID 找回。
    restarted = TraceStore(capacity=10, directory=directory)
    got = restarted.get(trace_id)
    assert got is not None
    assert got["trace_id"] == trace_id
    assert got["plan"] == {"intent": "data"}


def test_trace_store_ids_unique_across_restart(tmp_path):
    directory = tmp_path / "traces"
    store = TraceStore(capacity=10, directory=directory)
    first = [store.new_id("2026-09-01") for _ in range(3)]
    for trace_id in first:
        store.save(_make_trace(trace_id))

    restarted = TraceStore(capacity=10, directory=directory)
    second = [restarted.new_id("2026-09-01") for _ in range(3)]
    assert not (set(first) & set(second)), "重启后编号不能重复"


def test_trace_store_capacity_bound(tmp_path):
    directory = tmp_path / "traces"
    store = TraceStore(capacity=3, directory=directory)
    ids = [store.new_id("2026-09-01") for _ in range(5)]
    for trace_id in ids:
        store.save(_make_trace(trace_id))

    assert len(list(directory.glob("t-*.json"))) <= 3
    assert store.get(ids[-1]) is not None
    assert store.get(ids[0]) is None  # 超出容量后被淘汰


def test_trace_store_redacts_key_on_disk(tmp_path):
    secret = "sk-secret-key-abcdef123456"
    directory = tmp_path / "traces"
    store = TraceStore(capacity=10, directory=directory)
    trace_id = store.new_id("2026-09-01")
    trace = Trace(trace_id=trace_id, question="q", mode="live")
    trace.error("llm", RuntimeError("响应回显了 %s" % secret))

    def redactor(value):
        if isinstance(value, str):
            return redact_secret(value, secret)
        if isinstance(value, dict):
            return {key: redactor(item) for key, item in value.items()}
        if isinstance(value, list):
            return [redactor(item) for item in value]
        return value

    store.save(trace, redactor=redactor)
    on_disk = (directory / ("%s.json" % trace_id)).read_text(encoding="utf-8")
    assert secret not in on_disk
    assert secret not in json.dumps(store.get(trace_id), ensure_ascii=False)
    assert "***" in on_disk


def test_trace_store_prunes_on_startup(tmp_path):
    directory = tmp_path / "traces"
    store = TraceStore(capacity=2, directory=directory)
    for _ in range(4):
        store.save(_make_trace(store.new_id("2026-09-01")))
    # 新实例启动时也要按容量剪枝。
    TraceStore(capacity=2, directory=directory)
    assert len(list(directory.glob("t-*.json"))) <= 2


def test_tool_step_records_failure_branch():
    trace = Trace("t-x", "q")
    trace.tool(tool="run_sql", params={"sql": "SELECT 1"}, status="error",
               result={"error": "没有 FROM"}, took_ms=1.5, accepted=False,
               reject_reason="没有 FROM", source="live")
    entry = trace.tools[0]
    assert entry["status"] == "error"
    assert entry["accepted"] is False
    assert entry["reject_reason"] == "没有 FROM"
    assert entry["took_ms"] == 1.5
    assert entry["result_preview"]


# -- 并发隔离 -------------------------------------------------------------------


def test_trace_objects_do_not_share_state():
    a = Trace("t-a", "qa")
    b = Trace("t-b", "qb")
    a.step("plan", {"intent": "data"})
    a.tool(tool="query_metrics", params={"start": "x"}, status="ok", accepted=True)
    assert a.plan == {"intent": "data"}
    assert b.plan == {}
    assert b.tools == []
    assert all(step["step"] != "plan" for step in b.steps)


# -- 清理旧 trace 绝不能把请求带崩（实测过的 500） ------------------------------


def _make_store(tmp_path, capacity: int) -> TraceStore:
    store = TraceStore(capacity=capacity, directory=tmp_path / "traces")
    return store


def _save_one(store: TraceStore, n: int) -> Trace:
    trace = Trace("t-20260901-%04d" % n, question="q%d" % n)
    trace.answer = {"type": "data"}
    store.save(trace)
    return trace


def test_prune_failure_never_escapes_save(tmp_path, monkeypatch):
    """删旧 trace 失败（例如环境里有批量删除保护）不能让 save() 抛出。

    实测过的现场：var/traces 累计 239 个文件 > 容量 200，一次要删 39 个 →
    被批量删除保护拦下 → 异常从 save() 冒到 /api/chat，之后每个请求都是 HTTP 500。
    """
    from pathlib import Path as _Path

    store = _make_store(tmp_path, capacity=1)
    for i in range(4):
        _save_one(store, i)

    def blocked(self, *args, **kwargs):
        raise SystemExit("[safe-delete] 批量删除被拦住")

    monkeypatch.setattr(_Path, "unlink", blocked)

    trace = _save_one(store, 99)  # 不能抛
    assert store.last_error, "失败了要留下痕迹"
    assert "SystemExit" in store.last_error
    # 记录本身仍要在内存里拿得到（落盘成功在前，清理失败在后）
    assert store.get(trace.trace_id) is not None


def test_prune_caps_deletions_per_call(tmp_path):
    """单次清理最多删 PRUNE_PER_SAVE 个——"一次删一大批"正是会被拦下的形态。

    注意只量**一次** `_prune()` 的删除量：TraceStore 在构造时（`_load_existing`）也会清理一次，
    把两次混在一起算就测不出单次上限。
    """
    from kbqa.trace import PRUNE_PER_SAVE

    directory = tmp_path / "traces"
    bulk = TraceStore(capacity=1000, directory=directory)
    for i in range(30):
        _save_one(bulk, i)
    assert len(list(directory.glob("t-*.json"))) == 30

    small = TraceStore(capacity=2, directory=directory)
    before = len(list(directory.glob("t-*.json")))

    small._prune()  # 只调一次

    after = len(list(directory.glob("t-*.json")))
    removed = before - after
    assert 0 < removed <= PRUNE_PER_SAVE, (before, after)
    assert after > 2, "一次不该把超出容量的全清掉（还剩 %d 个）" % after


def test_chat_is_still_200_when_prune_explodes(client, monkeypatch):
    """端到端：清理炸了也不能变成 HTTP 500。"""
    from kbqa.trace import TraceStore

    calls = {"n": 0}

    def boom(self):
        calls["n"] += 1
        raise SystemExit("[safe-delete] blocked")

    monkeypatch.setattr(TraceStore, "_prune", boom)

    resp = client.post(
        "/api/chat", json={"session_id": "prune-boom", "question": "7 月整体的净营业额是多少？"}
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["answer"], body
    assert body["trace_id"]
    assert calls["n"] >= 1, "确认这次真的走了会抛异常的清理路径"
    # 即使清理炸了，这条 trace 仍然应该能按 ID 取回
    assert client.get("/api/trace/%s" % body["trace_id"]).status_code == 200

