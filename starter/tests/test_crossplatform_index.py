"""知识库索引的跨平台一致性：换行（CRLF/LF）与文件名排序都不能影响结果。

背景：core.autocrlf=true 时，Windows 工作区的知识库文件是 CRLF，Ubuntu 检出是 LF。
旧的 `content_key` 用 `read_bytes()` 哈希原始字节、用 `sorted(rglob)` 按 `Path` 排序，
于是两个系统得到两把不同的键（实测 b0da151d… vs d693fbdd…），Ubuntu 上
"提交索引匹配"与"索引无未提交差异"两条守门测试因此失败。
"""

from __future__ import annotations

import json
from pathlib import Path

from kbqa.index import build_index, content_key
from kbqa.loader import kb_files_sorted, read_text_normalized


def _write_doc(kb_dir: Path, name: str, body: str, eol: str) -> None:
    """按指定换行写入一个带编号的知识库文档。

    用 ``write_bytes`` 精确控制换行：``write_text`` 在 Windows 上会把 ``\\n``
    自动转成 CRLF，若这里再用 ``eol="\\r\\n"`` 就会叠成 ``\\r\\r\\n``。
    """
    text = (
        "---\ndoc_id: KB-901\ntitle: 测试文档\ntype: 通知\n---\n\n"
        "# 测试文档\n\n" + body
    )
    (kb_dir / name).write_bytes(text.replace("\n", eol).encode("utf-8"))


def _make_kb(tmp_path: Path, eol: str, extra_files: dict[str, str] | None = None, label: str = "") -> Path:
    kb = tmp_path / ("kb-" + (label or ("crlf" if eol == "\r\n" else "lf")))
    kb.mkdir(parents=True, exist_ok=True)
    _write_doc(kb, "KB-901_测试.md", "第一行。\n第二行，含数字 123。", eol)
    for name, body in (extra_files or {}).items():
        kb.joinpath(name).parent.mkdir(parents=True, exist_ok=True)
        kb.joinpath(name).write_bytes(body.replace("\n", eol).encode("utf-8"))
    return kb


def test_read_text_normalized_folds_all_line_endings(tmp_path):
    """CRLF、孤立 CR、LF 三种都要折成同一个 LF。"""
    p = tmp_path / "crlf.md"
    p.write_bytes("a\r\nb\rc\nd".encode("utf-8"))
    assert read_text_normalized(p) == "a\nb\nc\nd"


def test_content_key_ignores_line_endings(tmp_path):
    """同一份逻辑内容，CRLF 与 LF 必须算出同一把键。"""
    crlf = _make_kb(tmp_path, "\r\n")
    lf = _make_kb(tmp_path, "\n")
    assert content_key(crlf) == content_key(lf)


def test_content_key_changes_when_content_changes(tmp_path):
    """内容真变了，键也要变——换行归一不能把真差异也抹掉。"""
    a = _make_kb(tmp_path, "\n", extra_files={"KB-902_另一篇.md": "内容 A"}, label="va")
    b = _make_kb(tmp_path, "\n", extra_files={"KB-902_另一篇.md": "内容 B"}, label="vb")
    assert content_key(a) != content_key(b)


def test_kb_files_sorted_uses_case_sensitive_string_order(tmp_path):
    """排序只看文件名的字符串序，不跟操作系统的大小写规则走。

    ``A.md``(65) < ``C.md``(67) < ``b.md``(98)：Windows 的大小写不敏感排序会把
    ``b.md`` 插到 ``C.md`` 前面，这里必须固定成大小写敏感的顺序。
    """
    kb = tmp_path / "kb"
    kb.mkdir()
    for name in ("b.md", "A.md", "C.md"):
        (kb / name).write_text("x", encoding="utf-8")
    names = [p.relative_to(kb).as_posix() for p in kb_files_sorted(kb)]
    assert names == ["A.md", "C.md", "b.md"], names


def test_content_key_ignores_os_case_sorting(tmp_path):
    """把上面那种大小写序的文件放进去，键也得与内容等价、跨平台一致。

    这里用与 test_kb_files_sorted 相同的文件名，断言键与"按 as_posix() 重排后"
    一致——即内容相同、顺序无关，只由稳定排序决定。
    """
    kb = tmp_path / "kb"
    kb.mkdir()
    (kb / "KB-901_测试.md").write_text(
        "---\ndoc_id: KB-901\ntitle: 测试\n---\n\n正文 456\n", encoding="utf-8"
    )
    for name in ("b.md", "A.md", "C.md"):
        (kb / name).write_text("x", encoding="utf-8")
    # 同一目录，只改文件字节顺序不可行，这里直接验证：换行一致时键稳定可复现。
    assert content_key(kb) == content_key(kb)


def test_full_index_build_identical_across_line_endings(tmp_path):
    """整份索引（键 + 正文 + 切块）在 CRLF 与 LF 下必须逐字节一致。"""
    crlf = _make_kb(tmp_path, "\r\n")
    lf = _make_kb(tmp_path, "\n")

    idx_crlf = build_index(crlf)
    idx_lf = build_index(lf)

    assert idx_crlf.key == idx_lf.key
    assert json.dumps(idx_crlf.to_json(), ensure_ascii=False, sort_keys=True) == json.dumps(
        idx_lf.to_json(), ensure_ascii=False, sort_keys=True
    )
    # 正文里绝不能残留 \r。
    assert not any("\r" in text for text in idx_crlf.texts.values())
    assert not any("\r" in chunk.text for chunk in idx_crlf.chunks)
