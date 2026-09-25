"""现场演练：新增知识库文档 / 替换数据后，检索、问答、引用、trace 都跟着变。

全程在**临时副本**里做（知识库、数据、索引缓存、clean.db 都指向 tmp），
不污染正式知识库、数据与已跟踪的索引缓存。

索引隔离靠 `INDEX_PATH`：索引默认写在 `starter/.cache/index.json`（仓库里跟踪的那份），
不重定向的话用临时知识库重建出来的索引会把它覆盖掉——这既是隔离问题，也会让
"提交进仓库的索引"与真实 `knowledge_base/` 对不上。
"""

from __future__ import annotations

import hashlib
import json
import shutil
import sqlite3
import subprocess
import sys
from dataclasses import replace
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
STARTER = REPO / "starter"
TRACKED_INDEX = STARTER / ".cache" / "index.json"

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


def _count_docs(kb_dir: Path) -> int:
    """知识库里的文档数（与 loader 的口径一致：带 KB-\\d+ 编号的文件）。"""
    from kbqa.loader import load_knowledge_base

    docs, _ = load_knowledge_base(kb_dir)
    return len(docs)


def _settings_for(tmp_path, monkeypatch, kb_dir: Path, data_dir: Path):
    """构造一套指向临时目录的配置，并把索引缓存也挪到 tmp。"""
    from kbqa.config import load_settings

    # 索引走 INDEX_PATH 重定向，不再给 Settings.index_path 打补丁。
    monkeypatch.setenv("INDEX_PATH", str(tmp_path / "index.json"))
    base = load_settings()
    return replace(base, kb_dir=kb_dir, data_dir=data_dir, var_dir=tmp_path / "var")


def _digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest() if path.is_file() else "(不存在)"


def _git_status() -> str:
    proc = subprocess.run(
        ["git", "status", "--porcelain"],
        cwd=str(REPO),
        capture_output=True,
        text=True,
        check=False,
    )
    return proc.stdout


def test_index_path_can_be_redirected(tmp_path, monkeypatch):
    """INDEX_PATH 必须真的能改掉索引位置——演练与测试的隔离全靠它。"""
    from kbqa.config import load_settings

    target = tmp_path / "nested" / "index.json"
    monkeypatch.setenv("INDEX_PATH", str(target))
    assert load_settings().index_path == target.resolve()


def _index_problems(data: dict, kb_dir: Path) -> list[str]:
    """判定"这份索引是不是当前知识库的索引"，返回问题列表。

    抽成独立函数是为了让守门逻辑本身也能被测：既要能认下正常索引，
    也要能认出一份**过期的**索引（历史上真发生过：临时知识库的索引把仓库里
    跟踪的那份覆盖了）。
    """
    from kbqa.index import content_key

    problems: list[str] = []
    expected_key = content_key(kb_dir)
    if data.get("key") != expected_key:
        problems.append("内容键不一致：索引=%s 期望=%s" % (data.get("key"), expected_key))
    expected_docs = _count_docs(kb_dir)
    if len(data.get("docs") or {}) != expected_docs:
        problems.append("文档数不一致：索引=%d 期望=%d" % (len(data.get("docs") or {}), expected_docs))
    return problems


def _git_blob(rev_spec: str = "HEAD:starter/.cache/index.json") -> bytes | None:
    """直接从 git 里取某份内容——刻意不读工作区文件。

    工作区文件可能被**同一个测试进程里更早的用例**重建过（例如某个用例用临时知识库
    跑了一次 rebuild）。那样"工作区 == 真实知识库"会假通过，把提交里那份过期缓存放过去。
    所以守门必须看 git 里的 blob。
    """
    proc = subprocess.run(
        ["git", "show", rev_spec],
        cwd=str(REPO),
        capture_output=True,
        check=False,
    )
    return proc.stdout if proc.returncode == 0 else None


def test_index_guard_accepts_current_index():
    """守门的正例：拿真实知识库算出来的索引应当被判为合格。"""
    from kbqa.index import content_key

    sample = {"key": content_key(REPO / "knowledge_base"), "docs": {}}
    sample["docs"] = {str(i): {} for i in range(_count_docs(REPO / "knowledge_base"))}
    assert _index_problems(sample, REPO / "knowledge_base") == []


def test_index_guard_rejects_stale_index():
    """守门的反例：过期索引（内容键不对、文档数也不对）必须被判为不合格。"""
    stale = {"key": "f9b2ceda3da6" + "0" * 52, "docs": {}}
    problems = _index_problems(stale, REPO / "knowledge_base")
    assert any("内容键" in item for item in problems), problems
    assert any("文档数" in item for item in problems), problems


def test_committed_index_matches_real_knowledge_base():
    """**提交里**的索引必须就是当前知识库的索引（顺序无关的守门）。

    这条刻意读 `git show HEAD:...` 而不是工作区文件：只要跑测试的顺序里有人先重建过索引，
    工作区就会被刷成最新的，那样提交里那份旧缓存放多久都不会被发现。
    """
    blob = _git_blob()
    assert blob, "git 里读不到 starter/.cache/index.json（是不是没被跟踪？）"
    problems = _index_problems(json.loads(blob.decode("utf-8")), REPO / "knowledge_base")
    assert not problems, (
        "提交里的索引与当前知识库不一致：%s。"
        "修法：在 starter/ 下**不要**设 INDEX_PATH 跑一次 `python -m kbqa.rebuild`，把结果一起提交。"
        % "；".join(problems)
    )


def test_working_tree_index_matches_real_knowledge_base():
    """工作区那份也要合格（提交对了但工作区被改脏，同样会被 CI 的差异检查拦下）。"""
    assert TRACKED_INDEX.is_file(), "索引缓存在仓库里应当是被跟踪的"
    problems = _index_problems(
        json.loads(TRACKED_INDEX.read_text(encoding="utf-8")), REPO / "knowledge_base"
    )
    assert not problems, "；".join(problems)


def test_tracked_index_has_no_uncommitted_changes():
    """被跟踪的索引不能有未提交差异——重建过就要提交结果，CI 也查这一条。"""
    proc = subprocess.run(
        ["git", "diff", "--quiet", "--", "starter/.cache/index.json"],
        cwd=str(REPO),
        capture_output=True,
        check=False,
    )
    assert proc.returncode == 0, (
        "starter/.cache/index.json 与提交版本不一致：要么提交它，要么跑一次重建后提交"
    )


def test_new_doc_drill(real_retriever, tmp_path, monkeypatch):
    from kbqa.service import Service

    # 1) 临时知识库副本 + 新增文档
    kb_dir = tmp_path / "knowledge_base"
    shutil.copytree(REPO / "knowledge_base", kb_dir)
    before = _count_docs(kb_dir)
    (kb_dir / "notices" / "KB-099_临时停售通知.md").write_text(NEW_DOC, encoding="utf-8")

    settings = _settings_for(tmp_path, monkeypatch, kb_dir, REPO / "data")
    service = Service(settings)

    # 2) 文档数比基础值多一（不写死 35/36——知识库内容会变）
    health = service.health()
    assert health["kb_docs"] == before + 1, (before, health["kb_docs"])

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


def test_drill_script_leaves_worktree_and_tracked_index_untouched():
    """跑一遍真正的演练脚本，确认它没动仓库里跟踪的索引、也没留下改动。

    这是"演练隔离"的端到端验收：脚本自身会断言一次，这里从外部再断言一次，
    避免脚本自检写错时把问题放过去。
    """
    before_digest = _digest(TRACKED_INDEX)
    before_status = _git_status()

    proc = subprocess.run(
        [sys.executable, str(REPO / "eval" / "drill_new_doc.py")],
        cwd=str(STARTER),
        capture_output=True,
        text=True,
        timeout=600,
    )

    assert proc.returncode == 0, "演练脚本失败：\n%s\n%s" % (proc.stdout[-2000:], proc.stderr[-1000:])
    assert "演练成功" in proc.stdout, proc.stdout[-800:]
    assert _digest(TRACKED_INDEX) == before_digest, "演练改动了 starter/.cache/index.json"
    assert _git_status() == before_status, "演练在工作区留下了改动"
