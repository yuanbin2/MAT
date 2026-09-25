"""配置自检：打印当前环境推导出的模型模式与 `.env` 装载情况。

用法：

    python -m kbqa.envcheck            # key=value 行，便于人看与脚本 grep
    python -m kbqa.envcheck --json     # 同一份信息，便于测试解析

存在的理由：`.env` 读没读进去，光看服务是分不出来的——配置缺失只会静默退化成 mock。
`make env-mode` 就是它的包装，用来排查"我明明配了 Key，为什么还是 mock"。
刻意**不打印 Key 本身**，只打印有没有值和长度。
"""

from __future__ import annotations

import json
from typing import Any

from .config import (
    env_files_to_load,
    load_env_files,
    load_settings,
    parse_env_file,
)


def inspect() -> dict[str, Any]:
    """不修改环境，只报告"如果现在起服务会是哪种模式"。"""
    candidates = env_files_to_load()
    existing = [path for path in candidates if path.is_file()]
    loaded = load_env_files(candidates)
    settings = load_settings()

    without_keys: list[str] = []
    for path in existing:
        try:
            text = path.read_text(encoding="utf-8-sig")
        except OSError:
            continue
        # 文件在、但一行有效赋值都没有：最常见的原因是整份被注释掉了。
        if not parse_env_file(text):
            without_keys.append(str(path))

    return {
        "llm_mode": settings.llm_mode,
        "env_file_candidates": [str(path) for path in candidates],
        "env_files_found": [str(path) for path in existing],
        "env_files_loaded": [str(path) for path in loaded],
        "env_files_without_keys": without_keys,
        "api_key": "set" if settings.llm_api_key else "empty",
        "api_key_length": len(settings.llm_api_key),
        "base_url": settings.llm_base_url,
        "model": settings.llm_model,
        "today": settings.today.isoformat(),
        "chat_budget": settings.chat_budget,
        "llm_timeout": settings.llm_timeout,
    }


def main(argv: list[str] | None = None) -> int:
    import argparse

    parser = argparse.ArgumentParser(description="打印当前配置推导出的模型模式")
    parser.add_argument("--json", action="store_true", help="以 JSON 输出")
    args = parser.parse_args(argv)

    report = inspect()
    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
        return 0

    print("llm_mode=%s" % report["llm_mode"])
    print("env_files_found=%d" % len(report["env_files_found"]))
    print("env_files_loaded=%d" % len(report["env_files_loaded"]))
    print("api_key=%s" % report["api_key"])
    print("base_url=%s" % (report["base_url"] or "(空)"))
    print("model=%s" % (report["model"] or "(空)"))
    for path in report["env_files_without_keys"]:
        print("warning=%s 里没有任何有效赋值（是不是整份被注释掉了？）" % path)
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
