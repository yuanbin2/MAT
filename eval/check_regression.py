#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""评测回归判定：把新报告和仓库里跟踪的 mock 基线对比，退步就返回非零。

`eval/run_eval.py` 即使失分也返回退出码 0，不能直接拿它当 CI 门禁；这个脚本补上这一步：

- 比较**总分、各分类得分、每题得分与通过状态**；
- 题目缺失、报告格式异常、任何既有题退步 → 非零退出；
- 输出失败题号、类别、失败检查项与 trace_id，便于直接进调试面板。

只比较业务结果，不比较生成时间、机器上的绝对路径或端口。
基线用 `--update` 从一份当前报告生成，提交时注明 commit、题库与 llm_mode=mock。
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


def compare(baseline: dict, current: dict) -> list[dict]:
    """返回问题列表；空列表表示没有退步。"""
    problems: list[dict] = []

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
    for qid, before in b_questions.items():
        after = c_questions.get(qid)
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


def format_problems(problems: list[dict]) -> str:
    if not problems:
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

    regressions = compare(baseline, current)
    print(format_problems(regressions))
    total = current.get("total", {})
    print(
        "当前：earned=%s/%s questions=%s passed=%s"
        % (total.get("earned"), total.get("points"), total.get("questions"), total.get("passed"))
    )
    return EXIT_REGRESSION if regressions else EXIT_OK


if __name__ == "__main__":
    sys.exit(main())
