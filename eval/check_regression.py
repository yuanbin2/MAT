#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""评测回归判定：把新报告和仓库里跟踪的 mock 基线对比，退步就返回非零。

`eval/run_eval.py` 即使失分也返回退出码 0，不能直接拿它当 CI 门禁；这个脚本补上这一步：

- 比较**总分、各分类得分、每题得分与通过状态**；
- 题目缺失、报告格式异常、任何既有题退步 → 非零退出；
- 输出失败题号、类别、失败检查项与 trace_id，便于直接进调试面板。

只比较业务结果，不比较生成时间、机器上的绝对路径或端口。
基线用 `--update` 从一份当前报告生成，提交时注明 commit、题库与 llm_mode=mock。

调试时如果只跑了部分题目（`run_eval.py --only <类别>`），**不能**直接跟全量基线比——
总分与分类分都不可比，只会刷出一堆"缺题"。这种情况用 `--subset`：
它只比新报告里出现过的题目，并明确声明总分/分类分未比较。默认不加参数仍是全量严格比较。
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

EXIT_OK = 0
EXIT_REGRESSION = 1
EXIT_REPORT_ERROR = 2

#: 浮点比较容差：得分是 0.5 的倍数，1e-6 足够。
EPS = 1e-6
#: 这些字段随机器/时间变化，不参与比较。
IGNORED_TOP_LEVEL = ("generated_at", "base_url", "questions_file", "kb_dir", "latency_seconds", "timeout")


def load_report(path: Path) -> tuple[dict | None, list[str]]:
    """读报告；格式异常时返回（None，问题列表）。"""
    if not path.exists():
        return None, ["报告不存在：%s" % path]
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except OSError as exc:
        return None, ["报告读不出来：%s" % exc]
    except ValueError as exc:
        return None, ["报告不是合法 JSON：%s" % exc]
    if not isinstance(data, dict):
        return None, ["报告顶层不是对象"]

    problems: list[str] = []
    total = data.get("total")
    if not isinstance(total, dict) or not isinstance(total.get("earned"), (int, float)):
        problems.append("报告缺少 total.earned")
    questions = data.get("questions")
    if not isinstance(questions, list):
        problems.append("报告缺少 questions 数组")
    elif not questions:
        problems.append("questions 为空")
    else:
        for index, item in enumerate(questions):
            if not isinstance(item, dict) or "id" not in item:
                problems.append("questions[%d] 缺少 id" % index)
                break
    if problems:
        # 格式有问题就不把这份报告交给调用方，免得误用。
        return None, problems
    return data, problems


def _earned(node, default=0.0) -> float:
    if isinstance(node, dict) and isinstance(node.get("earned"), (int, float)):
        return float(node["earned"])
    return default


def _failed_checks(question: dict) -> list[str]:
    failed: list[str] = []
    for turn in question.get("turns") or []:
        if not isinstance(turn, dict):
            continue
        for check in turn.get("checks") or []:
            if isinstance(check, dict) and check.get("passed") is False:
                name = check.get("name") or "?"
                failed.append(name)
    return failed


def _trace_id(question: dict) -> str | None:
    for turn in question.get("turns") or []:
        if isinstance(turn, dict) and isinstance(turn.get("trace_id"), str):
            return turn["trace_id"]
    return None


def compare(baseline: dict, current: dict, *, subset: bool = False) -> list[dict]:
    """返回问题列表；空列表表示没有退步。

    ``subset=True`` 是给"只跑了一部分题"用的局部比较（例如调试时 `run_eval.py --only doc`）：
    只比对**新报告里出现过**的题目。总分与分类分不比较——局部跑出来的总分没有可比性，
    拿它跟全量基线比只会得到一堆假回归。

    局部比较的覆盖面天然变小，所以必须显式加参数；不加就是原来的全量严格比较
    （基线里有题而新报告没有 → 直接判"缺题"，防止靠删题让 CI 变绿）。
    """
    problems: list[dict] = []

    if not subset:
        b_total = _earned(baseline.get("total"), None)  # type: ignore[arg-type]
        c_total = _earned(current.get("total"))
        if b_total is not None and c_total + EPS < b_total:
            problems.append(
                {"kind": "total", "detail": "总分 %s -> %s" % (b_total, c_total)}
            )

        b_cats = baseline.get("per_category") or {}
        c_cats = current.get("per_category") or {}
        if isinstance(b_cats, dict):
            for name, node in b_cats.items():
                if name not in c_cats:
                    problems.append(
                        {"kind": "category", "category": name, "detail": "新报告缺少类别 %s" % name}
                    )
                    continue
                if _earned(c_cats.get(name)) + EPS < _earned(node):
                    problems.append(
                        {
                            "kind": "category",
                            "category": name,
                            "detail": "类别 %s 得分 %s -> %s"
                            % (name, _earned(node), _earned(c_cats.get(name))),
                        }
                    )

    b_questions = {
        item["id"]: item
        for item in (baseline.get("questions") or [])
        if isinstance(item, dict) and "id" in item
    }
    c_questions = {
        item["id"]: item
        for item in (current.get("questions") or [])
        if isinstance(item, dict) and "id" in item
    }

    if subset:
        # 只看新报告里出现的题目；基线里没有的题目无法比较，也要报出来。
        pairs = list(c_questions.items())
    else:
        pairs = [(qid, c_questions.get(qid)) for qid in b_questions]

    for qid, after in pairs:
        before = b_questions.get(qid)
        if before is None:
            problems.append(
                {
                    "kind": "unknown",
                    "id": qid,
                    "category": (after or {}).get("category"),
                    "detail": "基线里没有这道题，局部比较无从判定",
                }
            )
            continue
        if after is None:
            problems.append(
                {
                    "kind": "missing",
                    "id": qid,
                    "category": before.get("category"),
                    "detail": "题目缺失（不能靠删题让 CI 变绿）",
                }
            )
            continue
        regressed = False
        if before.get("passed") and not after.get("passed"):
            regressed = True
        elif _earned(after) + EPS < _earned(before):
            regressed = True
        if regressed:
            problems.append(
                {
                    "kind": "question",
                    "id": qid,
                    "category": after.get("category") or before.get("category"),
                    "detail": "通过/得分退步（%s -> %s）"
                    % (_earned(before), _earned(after)),
                    "failed_checks": _failed_checks(after),
                    "trace_id": _trace_id(after),
                }
            )
    return problems


def format_problems(problems: list[dict], *, subset: bool = False) -> str:
    if not problems:
        if subset:
            return "局部比较没有发现回归：新报告里出现的题目均不低于基线。"
        return "没有发现回归：总分、分类、逐题通过状态均不低于基线。"
    lines = ["发现 %d 处回归：" % len(problems)]
    for item in problems:
        kind = item.get("kind")
        if kind == "total":
            lines.append("  [总分] %s" % item["detail"])
        elif kind == "category":
            lines.append("  [分类] %s" % item["detail"])
        elif kind == "missing":
            lines.append(
                "  [缺题] %s（%s）%s" % (item.get("id"), item.get("category"), item["detail"])
            )
        elif kind == "unknown":
            lines.append(
                "  [基线无此题] %s（%s）%s"
                % (item.get("id"), item.get("category"), item["detail"])
            )
        else:
            extra = ""
            if item.get("failed_checks"):
                extra += "；失败检查：%s" % "、".join(item["failed_checks"])
            if item.get("trace_id"):
                extra += "；trace_id=%s" % item["trace_id"]
            lines.append(
                "  [逐题] %s（%s）%s%s"
                % (item.get("id"), item.get("category"), item["detail"], extra)
            )
    lines.append("把 trace_id 贴进前端调试面板即可定位。")
    return "\n".join(lines)


def prune_report(report: dict, note: str) -> dict:
    """基线只保留可比较的业务结果，去掉时间/地址/回答原文等易变内容。"""
    return {
        "note": note,
        "llm_mode": "mock",
        "total": report.get("total"),
        "per_category": report.get("per_category"),
        "questions": [
            {
                "id": item.get("id"),
                "category": item.get("category"),
                "points": item.get("points"),
                "earned": item.get("earned"),
                "passed": item.get("passed"),
            }
            for item in (report.get("questions") or [])
            if isinstance(item, dict)
        ],
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="评测回归判定（对比 mock 基线）")
    parser.add_argument("--report", default="report.json", help="新报告，默认 report.json")
    parser.add_argument(
        "--baseline", default="eval/baseline_mock.json", help="跟踪的基线，默认 eval/baseline_mock.json"
    )
    parser.add_argument("--update", action="store_true", help="用新报告覆盖基线并退出")
    parser.add_argument("--note", default="mock 基线（无 Key 降级模式）", help="写入基线时的说明")
    parser.add_argument(
        "--subset",
        action="store_true",
        help="局部比较：只比新报告里出现过的题目（调试时 --only <类别> 用），"
        "不比较总分与分类分；基线里没有的题号会报错。",
    )
    args = parser.parse_args(argv)

    current_path = Path(args.report)
    current, problems = load_report(current_path)
    if problems:
        print("报告格式有问题，判定为失败：")
        for item in problems:
            print("  -", item)
        return EXIT_REPORT_ERROR

    baseline_path = Path(args.baseline)
    if args.update:
        baseline_path.parent.mkdir(parents=True, exist_ok=True)
        baseline_path.write_text(
            json.dumps(prune_report(current, args.note), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        total = current.get("total", {})
        print(
            "已写入基线 %s：earned=%s/%s questions=%s passed=%s"
            % (
                baseline_path,
                total.get("earned"),
                total.get("points"),
                total.get("questions"),
                total.get("passed"),
            )
        )
        return EXIT_OK

    baseline, problems = load_report(baseline_path)
    if problems:
        print("基线格式有问题，判定为失败：")
        for item in problems:
            print("  -", item)
        return EXIT_REPORT_ERROR

    regressions = compare(baseline, current, subset=args.subset)
    total = current.get("total", {})
    if args.subset:
        print(
            "[局部比较] 只比对新报告里的 %s 道题；总分与分类分未比较（局部跑分与全量基线不可比）。"
            % total.get("questions")
        )
    print(format_problems(regressions, subset=args.subset))
    print(
        "当前：earned=%s/%s questions=%s passed=%s"
        % (total.get("earned"), total.get("points"), total.get("questions"), total.get("passed"))
    )
    return EXIT_REGRESSION if regressions else EXIT_OK


if __name__ == "__main__":
    sys.exit(main())
