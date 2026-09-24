"""loader：doc_id 以文件名为准，元数据冲突要明确告警。

用自建文档验证规则，不依赖原始知识库——换掉 knowledge_base/ 后这些用例照样成立。
"""

from __future__ import annotations

from kbqa.loader import load_document, load_knowledge_base


def test_doc_id_comes_from_filename(tmp_path):
    path = tmp_path / "KB-042_某门店通知.md"
    path.write_text("---\ntitle: 某门店通知\n---\n这是正文内容，足够长以便入库。\n", encoding="utf-8")
    document = load_document(path)
    assert document is not None
    assert document.doc_id == "KB-042"


def test_metadata_conflict_warns_and_filename_wins(tmp_path):
    path = tmp_path / "KB-042_某门店通知.md"
    path.write_text(
        "---\ndoc_id: KB-999\ntitle: 某门店通知\n---\n正文内容足够长。\n", encoding="utf-8"
    )
    document = load_document(path)
    assert document is not None
    # 文件名为准
    assert document.doc_id == "KB-042"
    # 冲突要告警，且说清以谁为准
    assert any("KB-999" in warning and "文件名为准" in warning for warning in document.warnings)


def test_file_without_kb_prefix_is_skipped(tmp_path):
    path = tmp_path / "README.md"
    path.write_text("# 说明\n这不是知识库文档。\n", encoding="utf-8")
    assert load_document(path) is None


def test_front_matter_id_cannot_rescue_prefixless_file(tmp_path):
    """文件名没有 KB 编号、只在 YAML 里写了 doc_id——同样不认（编号以文件名为准）。"""
    path = tmp_path / "临时说明.md"
    path.write_text("---\ndoc_id: KB-777\ntitle: 临时说明\n---\n正文。\n", encoding="utf-8")
    assert load_document(path) is None


def test_load_knowledge_base_surfaces_conflict_warning(tmp_path):
    (tmp_path / "KB-001_手册.md").write_text(
        "---\ndoc_id: KB-007\ntitle: 手册\n---\n正文一二三四五六七八。\n", encoding="utf-8"
    )
    documents, warnings = load_knowledge_base(tmp_path)
    assert [document.doc_id for document in documents] == ["KB-001"]
    assert any("不一致" in warning for warning in warnings)


def test_duplicate_doc_id_warns_once(tmp_path):
    (tmp_path / "KB-005_a.md").write_text("---\ntitle: A\n---\n正文一二三四五六七八。\n", encoding="utf-8")
    (tmp_path / "sub").mkdir()
    (tmp_path / "sub" / "KB-005_b.md").write_text(
        "---\ntitle: B\n---\n正文一二三四五六七八。\n", encoding="utf-8"
    )
    documents, warnings = load_knowledge_base(tmp_path)
    assert [document.doc_id for document in documents] == ["KB-005"]
    assert any("doc_id 重复" in warning for warning in warnings)
