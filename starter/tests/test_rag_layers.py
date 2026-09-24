"""会话隔离与切块的最小测试。"""

from __future__ import annotations

from kbqa.chunker import chunk_document
from kbqa.loader import Document
from kbqa.sessions import SessionStore


def test_sessions_isolated_by_id():
    store = SessionStore()
    store.append("A", {"question": "q1", "standalone": "s1", "slots": {}})
    store.append("B", {"question": "q2", "standalone": "s2", "slots": {}})
    assert [t["question"] for t in store.history("A")] == ["q1"]
    assert [t["question"] for t in store.history("B")] == ["q2"]
    # 交错追加不串线
    store.append("A", {"question": "q3", "standalone": "s3", "slots": {}})
    assert [t["question"] for t in store.history("A")] == ["q1", "q3"]
    assert [t["question"] for t in store.history("B")] == ["q2"]


def test_sessions_no_session_id_returns_empty():
    store = SessionStore()
    store.append(None, {"question": "q", "standalone": "s", "slots": {}})
    assert store.history(None) == []


def _doc(text, doc_id="KB-999", title="T"):
    return Document(doc_id=doc_id, title=title, text=text, path=None, fmt="md")


def test_chunker_covers_tail():
    # 301 字文档：末尾那 1 个字也不能丢。
    text = "字" * 301
    chunks = chunk_document(_doc(text))
    joined = "".join(c.text for c in chunks)
    assert len(joined) >= 301
    assert joined.startswith("字" * 301) or "字" * 301 in joined


def test_chunker_keeps_heading_context():
    text = "## 退款政策\n外卖订单 24 小时内可退款。"
    chunks = chunk_document(_doc(text))
    # 至少有一块的 heading 带章节标题
    assert any("退款政策" in c.heading for c in chunks)


def test_chunker_table_kind():
    text = "| 商品 | 过敏原 |\n|---|---|\n| 牛肉poke | 麸质 |"
    chunks = chunk_document(_doc(text))
    table = [c for c in chunks if c.kind == "table"]
    assert table, "表格应作为 table 块"
    assert table[0].table_header == ["商品", "过敏原"]
