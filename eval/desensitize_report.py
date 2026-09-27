"""把 live 评测的原始 report.json 脱敏后复制到 docs/eval/ 入库。

保留：model, code_commit, generated_at, total, per_category, questions（逐题含 turns/checks）。
剥掉：base_url、questions_file、kb_dir、timeout、only、顶层 latency、health、metrics_baselines 等
      指向本机路径或私有端点的字段。
闸门：命中 sk-/api_key/Bearer/secret/token/tp- 或本地绝对路径/私有端点即中断，不落盘。
"""
from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

KEEP_TOP = ("model", "code_commit", "generated_at", "total", "per_category", "questions")

FORBIDDEN = [
    r"sk-[A-Za-z0-9_\-]{8,}",
    r"api[_-]?key",
    r"Bearer\s",
    r"secret",
    r"token",
    r"tp-[A-Za-z0-9_\-]{8,}",
    r"[A-Za-z]:\\",
    r"/Users/",
    r"/home/",
    r"127\.0\.0\.1",
    r"localhost",
    r"api\.deepseek\.com",
    r"api\.stepfun\.com",
    r"\.venv",
    r"moneki-ai-takehome",
]


def git_commit() -> str:
    out = subprocess.run(
        ["git", "rev-parse", "--short", "HEAD"], cwd=ROOT, capture_output=True, text=True
    )
    return out.stdout.strip() if out.returncode == 0 else "unknown"


def sanitize(src: Path, dst: Path, model: str) -> None:
    raw = json.loads(src.read_text(encoding="utf-8"))
    out = {
        "model": model,
        "code_commit": git_commit(),
        "generated_at": raw["generated_at"],
        "total": raw["total"],
        "per_category": raw["per_category"],
        "questions": raw["questions"],
    }
    text = json.dumps(out, ensure_ascii=False, indent=2)
    hits = []
    for pat in FORBIDDEN:
        m = re.search(pat, text, re.I)
        if m:
            hits.append(f"{pat} -> {m.group(0)[:40]!r}")
    if hits:
        print(f"REFUSED {dst}: 命中禁词 {hits}", file=sys.stderr)
        sys.exit(1)
    dst.write_text(text + "\n", encoding="utf-8", newline="\n")
    t = out["total"]
    print(
        f"OK {dst.relative_to(ROOT)}  model={model} commit={out['code_commit']} "
        f"score={t['earned']}/{t['points']} passed={t['passed']}/{t['questions']}"
    )


if __name__ == "__main__":
    src, dst, model = Path(sys.argv[1]), Path(sys.argv[2]).resolve(), sys.argv[3]
    sanitize(src, dst, model)
