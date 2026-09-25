"""现场演练：新增知识库文档 / 替换数据后，检索、问答、引用、trace 都跟着变。

全程在**临时副本**里做（知识库、数据、索引缓存、clean.db 都指向 tmp），
不污染正式知识库、数据与已跟踪的索引缓存。
"""

from __future__ import annotations

import shutil
import sqlite3
from dataclasses import replace
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]

NEW_DOC = """---
doc_id: KB-099
title: S02 牛肉poke 临时停售通知
type: 通知
status: 现行
effective_from: 2026-08-20
---

# S02 牛肉poke 临时停售通知

因供应商临时召回原料，S02 门店的牛肉poke 自 2026 年 8 月 20 日起临时停售，
预计 8 月 22 日恢复供应。停售期间不做任何替代销售。
"""


def _settings_for(tmp_path, monkeypatch, kb_dir: Path, data_dir: Path):
    """构造一套指向临时目录的配置，并把索引缓存也挪到 tmp。"""
    from kbqa.config import Settings, load_settings

    # index_path 是属性、不随 env 变；直接给类打补丁，避免污染仓库 .cache/index.json。
    monkeypatch.setattr(Settings, "index_path", property(lambda self: tmp_path / "index.json"))
    base = load_settings()
    return replace(base, kb_dir=kb_dir, data_dir=data_dir, var_dir=tmp_path / "var")


def test_new_doc_drill(real_retriever, tmp_path, monkeypatch):
    from kbqa.service import Service

    # 1) 临时知识库副本 + 新增文档
    kb_dir = tmp_path / "knowledge_base"
    shutil.copytree(REPO / "knowledge_base", kb_dir)
    (kb_dir / "notices" / "KB-099_临时停售通知.md").write_text(NEW_DOC, encoding="utf-8")

    settings = _settings_for(tmp_path, monkeypatch, kb_dir, REPO / "data")
    service = Service(settings)

    # 2) 文档数跟着变
    health = service.health()
    assert health["kb_docs"] == 36, health["kb_docs"]

    # 3) /api/retrieve 能找到新文档
    found = service.retrieve("S02 牛肉poke 临时停售 供应商 召回", top_k=5)
    assert any(item["doc_id"] == "KB-099" for item in found["results"])

    # 4) /api/chat 能回答并正确引用它（真实检索，非桩件）
    out = service.chat("drill", "S02 的牛肉poke 为什么临时停售？")
    cited = [c["doc_id"] for c in out["citations"]]
    assert "KB-099" in cited, (out["answer_type"], out["answer"], cited)

    # 5) trace 里能看到新命中
    trace = service.get_trace(out["trace_id"])
    hit_docs = [hit["doc_id"] for r in trace["retrievals"] for hit in r["hits"]]
    assert "KB-099" in hit_docs, hit_docs
    assert trace["answer"]["citations"], "trace 要记下引用了哪篇"


def test_data_swap_reflected_in_answers(real_retriever, tmp_path, monkeypatch):
    from kbqa.service import Service

    data_dir = tmp_path / "data"
    shutil.copytree(REPO / "data", data_dir)
    db = data_dir / "pos.db"
    conn = sqlite3.connect(db)
    row = conn.execute(
        "SELECT order_id, date, store_id, product_id FROM sales "
        "WHERE amount IS NOT NULL AND amount != '' LIMIT 1"
    ).fetchone()
    conn.execute("UPDATE sales SET amount = '999.00' WHERE order_id = ?", (row[0],))
    conn.commit()
    conn.close()

    settings = _settings_for(tmp_path, monkeypatch, REPO / "knowledge_base", data_dir)
    service = Service(settings)

    # 改过的那一天/店/商品，金额必须来自新数据（metrics 走的就是 sales_clean）。
    metrics = service.metrics_summary(row[1], row[1], row[2], row[3])
    assert metrics["net_revenue"] == 999.0, metrics
    # 口径本身不变：清洗后的保留行数仍是 18290。
    assert service.tools.valid_sales_rows() == 18290
