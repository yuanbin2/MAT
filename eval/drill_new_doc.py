#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""现场演练：新增一篇知识库文档后，重建 + 重启服务，验证检索 / 问答 / 引用 / trace 都跟着变。

跑法（用装了依赖的 python）：

    cd starter && .venv/Scripts/python.exe ../eval/drill_new_doc.py

全程在临时副本里做，**不碰**正式 knowledge_base/、data/ 与已跟踪的索引缓存：
KB_DIR / DATA_DIR / VAR_DIR / INDEX_PATH 四个都指到临时目录，其中 INDEX_PATH 是关键——
索引默认写在 starter/.cache/index.json（仓库里跟踪的那份），不重定向的话临时知识库的索引
会把它覆盖掉，于是提交进仓库的索引与真实知识库对不上。脚本开头结尾会各算一次那个文件的
sha256，确认演练没动它。

演练完自动停掉服务并清理临时目录（`--keep` 可保留，方便手动查看）。

步骤与验收点（脚本会逐条打印 PASS/FAIL）：

 1. 复制知识库与数据到临时目录，启动服务 → 记下基础文档数；
 2. 往临时知识库加入一篇带唯一事实的新文档（编号自动挑一个没被占用的）；
 3. 用同一套环境变量执行 `python -m kbqa.rebuild` → 索引重建；
 4. 重启服务 → `/api/health` 的 kb_docs 比基础值**多一**、索引键变化；
 5. `/api/retrieve` 能找到新文档；
 6. `/api/chat` 能回答并引用它；
 7. `/api/trace/{id}` 里能看到新文档的命中片段。
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import socket
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parent
STARTER = REPO / "starter"

#: 仓库里跟踪的索引缓存——演练必须保证它一个字节都不变。
TRACKED_INDEX = STARTER / ".cache" / "index.json"

#: 优先用这些编号，被占用了就往上找。
DOC_ID_PREFERENCE = ("KB-099", "KB-098", "KB-097")

DOC_TEMPLATE = """---
doc_id: {doc_id}
title: S02 牛肉poke 临时停售通知
type: 通知
status: 现行
effective_from: 2026-08-20
---

# S02 牛肉poke 临时停售通知

因供应商临时召回原料，S02 门店的牛肉poke 自 2026 年 8 月 20 日起临时停售，
预计 8 月 22 日恢复供应。停售期间不做任何替代销售。
"""

QUESTION = "S02 的牛肉poke 为什么临时停售？"


def free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def http_json(url: str, payload: dict | None = None, timeout: float = 30.0):
    data = json.dumps(payload).encode("utf-8") if payload is not None else None
    headers = {"Content-Type": "application/json"} if data else {}
    request = urllib.request.Request(url, data=data, headers=headers)
    with urllib.request.urlopen(request, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


def wait_healthy(base: str, seconds: float = 40.0) -> dict:
    deadline = time.time() + seconds
    last: Exception | None = None
    while time.time() < deadline:
        try:
            return http_json(base + "/api/health", timeout=3)
        except (urllib.error.URLError, OSError) as exc:
            last = exc
            time.sleep(0.5)
    raise SystemExit("服务没有在 %s 秒内就绪：%s" % (seconds, last))


def start_service(env: dict, port: int) -> subprocess.Popen:
    return subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "kbqa.server:app", "--host", "127.0.0.1", "--port", str(port)],
        cwd=str(STARTER),
        env=env,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )


def stop(proc: subprocess.Popen | None) -> None:
    if proc is None:
        return
    proc.terminate()
    try:
        proc.wait(timeout=8)
    except subprocess.TimeoutExpired:
        proc.kill()


def file_digest(path: Path) -> str:
    if not path.is_file():
        return "(不存在)"
    return hashlib.sha256(path.read_bytes()).hexdigest()


def pick_doc_id(kb_dir: Path) -> str:
    """挑一个知识库里没被占用的编号。

    演练要验证的是"多了一篇文档"，不是某个固定编号；原样写死 KB-099 的话，
    源知识库里本来就有 KB-099 时文件数不会增加，断言就会莫名其妙地失败。
    """
    used = set()
    for path in kb_dir.rglob("*"):
        if path.is_file():
            match = re.match(r"^(KB-\d+)", path.name)
            if match:
                used.add(match.group(1))
    for candidate in DOC_ID_PREFERENCE:
        if candidate not in used:
            return candidate
    number = 100
    while "KB-%03d" % number in used:
        number += 1
    return "KB-%03d" % number


def main() -> int:
    parser = argparse.ArgumentParser(description="现场新增知识库文档演练")
    parser.add_argument("--keep", action="store_true", help="保留临时目录，便于手动查看")
    args = parser.parse_args()

    work = Path(tempfile.mkdtemp(prefix="moneki-drill-"))
    kb_dir = work / "knowledge_base"
    data_dir = work / "data"
    var_dir = work / "var"
    index_path = work / "index.json"
    shutil.copytree(REPO / "knowledge_base", kb_dir)
    shutil.copytree(REPO / "data", data_dir)
    var_dir.mkdir(parents=True, exist_ok=True)

    env = dict(os.environ)
    for key in ("LLM_BASE_URL", "LLM_API_KEY", "LLM_MODEL"):
        env.pop(key, None)  # 强制 mock，不请求任何付费模型
    # 光删环境变量不够：服务启动时会从仓库根的 .env 把 LLM_* 补回来，
    # 所以还要显式关掉 .env 读取（ENV_FILE= 表示一个字都不读）。
    env["ENV_FILE"] = ""
    env.update(
        {
            "KB_DIR": str(kb_dir),
            "DATA_DIR": str(data_dir),
            "VAR_DIR": str(var_dir),
            # 关键：把索引也写到临时目录，别覆盖仓库里跟踪的那份。
            "INDEX_PATH": str(index_path),
        }
    )

    doc_id = pick_doc_id(kb_dir)
    new_doc = DOC_TEMPLATE.format(doc_id=doc_id)

    port = free_port()
    base = "http://127.0.0.1:%d" % port
    proc: subprocess.Popen | None = None
    checks: list[tuple[bool, str]] = []
    tracked_before = file_digest(TRACKED_INDEX)

    def record(ok: bool, text: str) -> None:
        checks.append((ok, text))
        print("  %s %s" % ("PASS" if ok else "FAIL", text))

    try:
        print("临时工作目录：%s" % work)
        print("本次新增文档编号：%s" % doc_id)
        print("\n[1] 启动服务（加新文档之前）")
        proc = start_service(env, port)
        health_before = wait_healthy(base)
        before_docs = health_before.get("kb_docs")
        record(isinstance(before_docs, int) and before_docs > 0, "基础 kb_docs=%s" % before_docs)
        record(index_path.is_file(), "临时索引已生成在 %s（没写到仓库的 .cache/）" % index_path)

        # 重建会重写 var/clean.db，而运行中的服务正持有它（Windows 会锁文件），
        # 所以先把服务停掉，再改文档 / 重建，最后重启。
        stop(proc)
        proc = None

        print("\n[2] 往临时知识库加入 %s" % doc_id)
        target_dir = kb_dir / "notices"
        target_dir.mkdir(parents=True, exist_ok=True)
        target = target_dir / ("%s_临时停售通知.md" % doc_id)
        target.write_text(new_doc, encoding="utf-8")
        record(True, "已写入 %s" % target.name)

        print("\n[3] 执行重建命令")
        rebuild = subprocess.run(
            [sys.executable, "-m", "kbqa.rebuild"],
            cwd=str(STARTER),
            env=env,
            capture_output=True,
            text=True,
        )
        record(rebuild.returncode == 0, "kbqa.rebuild 退出码=%s" % rebuild.returncode)
        if rebuild.returncode != 0:
            print(rebuild.stderr[-800:])

        print("\n[4] 重启服务，确认索引刷新")
        proc = start_service(env, port)
        health_after = wait_healthy(base)
        after_docs = health_after.get("kb_docs")
        record(
            after_docs == before_docs + 1,
            "kb_docs %s -> %s（期望比基础值多一）" % (before_docs, after_docs),
        )
        record(
            health_after.get("index_key") != health_before.get("index_key"),
            "索引键变化：%s -> %s" % (health_before.get("index_key"), health_after.get("index_key")),
        )

        print("\n[5] /api/retrieve 找到新文档")
        found = http_json(base + "/api/retrieve", {"query": "S02 牛肉poke 临时停售 供应商 召回", "top_k": 5})
        docs = [item["doc_id"] for item in found.get("results", [])]
        record(doc_id in docs, "命中 doc_id：%s" % docs)

        print("\n[6] /api/chat 回答并引用它")
        answer = http_json(base + "/api/chat", {"session_id": "drill", "question": QUESTION})
        cited = [item["doc_id"] for item in answer.get("citations", [])]
        record(answer.get("answer_type") in ("doc", "hybrid"), "answer_type=%s" % answer.get("answer_type"))
        record(doc_id in cited, "citations=%s" % cited)

        print("\n[7] /api/trace 里能看到新命中")
        trace = http_json(base + "/api/trace/%s" % answer.get("trace_id"))
        hit_docs = [hit["doc_id"] for r in trace.get("retrievals", []) for hit in r.get("hits", [])]
        record(doc_id in hit_docs, "trace 检索命中：%s" % hit_docs)
        record(bool(trace.get("answer", {}).get("citations")), "trace 记录了引用")
        record(trace.get("model_called") is False, "mock 模式 model_called=False")

        print("\n[8] 仓库里跟踪的索引缓存应毫发无伤")
        tracked_after = file_digest(TRACKED_INDEX)
        record(
            tracked_before == tracked_after,
            "starter/.cache/index.json 未被改动（sha256 %.12s）" % tracked_after,
        )
    finally:
        stop(proc)
        tracked_final = file_digest(TRACKED_INDEX)
        if tracked_final != tracked_before:  # 兜底：即使中途抛异常也要吼一声
            print("  FAIL 跟踪的索引缓存被演练改动了：%s -> %s" % (tracked_before[:12], tracked_final[:12]))
            checks.append((False, "跟踪的索引缓存被改动"))
        if args.keep:
            print("\n临时目录已保留：%s" % work)
        else:
            shutil.rmtree(work, ignore_errors=True)
            print("\n临时目录已清理")

    failed = [text for ok, text in checks if not ok]
    print("\n" + "=" * 60)
    print("演练%s：%d/%d 项通过" % ("成功" if not failed else "失败", len(checks) - len(failed), len(checks)))
    for text in failed:
        print("  FAIL:", text)
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
