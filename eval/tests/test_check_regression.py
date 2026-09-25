#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""`check_regression.py` 的自测：只依赖标准库。

运行：

    cd eval/tests
    python3 -m unittest test_check_regression -v

覆盖：分数下降、漏题、损坏报告都必须失败；没有变化必须通过；
分类退步、总分退步、CLI 退出码与 `--update` 基线写入。
"""

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "eval" / "check_regression.py"
sys.path.insert(0, str(ROOT / "eval"))

import check_regression as cr  # noqa: E402


def make_report(earned_by_question: dict[str, float], category_of: dict[str, str]) -> dict:
    questions = []
    for qid, earned in earned_by_question.items():
        questions.append(
            {
                "id": qid,
                "category": category_of[qid],
                "points": 2.0,
                "earned": earned,
                "passed": earned >= 2.0,
                "turns": [
                    {
                        "question": qid,
                        "passed": earned >= 2.0,
                        "trace_id": "t-20260901-%04d" % len(questions),
                        "checks": [{"name": "answer", "passed": earned >= 2.0}],
                    }
                ],
            }
        )
    total_earned = sum(earned_by_question.values())
    categories: dict[str, dict] = {}
    for qid, earned in earned_by_question.items():
        bucket = categories.setdefault(
            category_of[qid], {"points": 0.0, "earned": 0.0, "questions": 0, "passed": 0}
        )
        bucket["points"] += 2.0
        bucket["earned"] += earned
        bucket["questions"] += 1
        bucket["passed"] += 1 if earned >= 2.0 else 0
    return {
        "total": {
            "points": 2.0 * len(questions),
            "earned": total_earned,
            "questions": len(questions),
            "passed": sum(1 for e in earned_by_question.values() if e >= 2.0),
        },
        "per_category": categories,
        "questions": questions,
    }


class TestCompare(unittest.TestCase):
    def setUp(self) -> None:
        self.category_of = {"R01": "retrieval", "C01": "doc", "T01": "multi_turn"}
        self.baseline = make_report(
            {"R01": 2.0, "C01": 2.0, "T01": 2.0}, self.category_of
        )

    def test_identical_report_passes(self):
        self.assertEqual(cr.compare(self.baseline, self.baseline), [])

    def test_score_drop_fails_and_names_question(self):
        current = make_report({"R01": 2.0, "C01": 0.0, "T01": 2.0}, self.category_of)
        problems = cr.compare(self.baseline, current)
        kinds = {item["kind"] for item in problems}
        self.assertIn("question", kinds)
        self.assertIn("category", kinds)
        self.assertIn("total", kinds)
        question = next(item for item in problems if item["kind"] == "question")
        self.assertEqual(question["id"], "C01")
        self.assertEqual(question["category"], "doc")
        self.assertIn("answer", question["failed_checks"])
        self.assertTrue(question["trace_id"])

    def test_missing_question_fails(self):
        current = make_report({"R01": 2.0, "C01": 2.0}, self.category_of)
        problems = cr.compare(self.baseline, current)
        missing = [item for item in problems if item["kind"] == "missing"]
        self.assertEqual([item["id"] for item in missing], ["T01"])

    def test_extra_question_is_allowed(self):
        current = make_report({"R01": 2.0, "C01": 2.0, "T01": 2.0, "N01": 2.0}, {
            "R01": "retrieval", "C01": "doc", "T01": "multi_turn", "N01": "health",
        })
        self.assertEqual(cr.compare(self.baseline, current), [])

    def test_improvement_is_allowed(self):
        low = make_report({"R01": 1.0}, {"R01": "retrieval"})
        high = make_report({"R01": 2.0}, {"R01": "retrieval"})
        self.assertEqual(cr.compare(low, high), [])


class TestSubsetCompare(unittest.TestCase):
    """只跑了一部分题（--only <类别>）时的局部比较。

    直接拿局部报告跟全量基线比会刷出一堆"缺题"，那是假回归；`subset=True` 只比
    新报告里出现过的题目，并且**不比较总分与分类分**（局部跑分不可比）。
    """

    def setUp(self) -> None:
        self.category_of = {"R01": "retrieval", "C01": "doc", "T01": "multi_turn"}
        self.baseline = make_report({"R01": 2.0, "C01": 2.0, "T01": 2.0}, self.category_of)

    def test_subset_of_baseline_passes(self):
        partial = make_report({"C01": 2.0}, self.category_of)
        self.assertEqual(cr.compare(self.baseline, partial, subset=True), [])

    def test_subset_still_catches_regression(self):
        partial = make_report({"C01": 0.0}, self.category_of)
        problems = cr.compare(self.baseline, partial, subset=True)
        self.assertEqual([item["kind"] for item in problems], ["question"])
        self.assertEqual(problems[0]["id"], "C01")

    def test_subset_does_not_report_missing_questions(self):
        """局部报告的"缺题"不是回归——这正是不得不区分的原因。"""
        partial = make_report({"C01": 2.0}, self.category_of)
        problems = cr.compare(self.baseline, partial, subset=True)
        self.assertFalse([item for item in problems if item["kind"] == "missing"])
        # 同一条局部报告走全量比较就会刷出缺题与总分假回归
        strict = cr.compare(self.baseline, partial)
        self.assertTrue([item for item in strict if item["kind"] == "missing"])
        self.assertTrue([item for item in strict if item["kind"] == "total"])

    def test_subset_rejects_question_absent_from_baseline(self):
        partial = make_report({"C01": 2.0, "ZZ9": 2.0}, {
            "C01": "doc", "ZZ9": "doc",
        })
        problems = cr.compare(self.baseline, partial, subset=True)
        self.assertEqual([item["kind"] for item in problems], ["unknown"])
        self.assertEqual(problems[0]["id"], "ZZ9")


class TestSubsetCli(unittest.TestCase):
    def _write(self, path: Path, payload: dict) -> None:
        path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")

    def test_subset_flag_and_banner(self):
        category_of = {"R01": "retrieval", "C01": "doc"}
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            baseline = tmp_path / "baseline.json"
            report = tmp_path / "report.json"
            self._write(baseline, make_report({"R01": 2.0, "C01": 2.0}, category_of))
            self._write(report, make_report({"C01": 2.0}, category_of))

            strict = subprocess.run(
                [sys.executable, str(SCRIPT), "--report", str(report), "--baseline", str(baseline)],
                capture_output=True,
                text=True,
            )
            subset = subprocess.run(
                [
                    sys.executable,
                    str(SCRIPT),
                    "--report",
                    str(report),
                    "--baseline",
                    str(baseline),
                    "--subset",
                ],
                capture_output=True,
                text=True,
            )

        self.assertEqual(strict.returncode, cr.EXIT_REGRESSION, strict.stdout)
        self.assertEqual(subset.returncode, cr.EXIT_OK, subset.stdout)
        self.assertIn("局部比较", subset.stdout)
        self.assertIn("总分与分类分未比较", subset.stdout)


class TestLoadReport(unittest.TestCase):
    def test_missing_report(self):
        report, problems = cr.load_report(Path("/definitely/not/here.json"))
        self.assertIsNone(report)
        self.assertTrue(problems)

    def test_corrupt_json(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "bad.json"
            path.write_text("{not json", encoding="utf-8")
            report, problems = cr.load_report(path)
            self.assertIsNone(report)
            self.assertTrue(any("合法 JSON" in item for item in problems))

    def test_missing_keys(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "incomplete.json"
            path.write_text(json.dumps({"total": {"points": 1}}), encoding="utf-8")
            report, problems = cr.load_report(path)
            self.assertIsNone(report)
            self.assertTrue(any("questions" in item for item in problems))


class TestCli(unittest.TestCase):
    def _write(self, path: Path, payload: dict) -> None:
        path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")

    def test_cli_exit_codes(self):
        category_of = {"R01": "retrieval", "C01": "doc"}
        baseline = make_report({"R01": 2.0, "C01": 2.0}, category_of)
        same = make_report({"R01": 2.0, "C01": 2.0}, category_of)
        worse = make_report({"R01": 2.0, "C01": 0.0}, category_of)
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            base_path = tmp_path / "baseline.json"
            same_path = tmp_path / "same.json"
            worse_path = tmp_path / "worse.json"
            bad_path = tmp_path / "bad.json"
            self._write(base_path, baseline)
            self._write(same_path, same)
            self._write(worse_path, worse)
            bad_path.write_text("[]", encoding="utf-8")

            def run(report: Path):
                return subprocess.run(
                    [sys.executable, str(SCRIPT), "--report", str(report), "--baseline", str(base_path)],
                    capture_output=True,
                    text=True,
                )

            self.assertEqual(run(same_path).returncode, cr.EXIT_OK)
            self.assertEqual(run(worse_path).returncode, cr.EXIT_REGRESSION)
            self.assertEqual(run(bad_path).returncode, cr.EXIT_REPORT_ERROR)

    def test_update_writes_pruned_baseline(self):
        report = make_report({"R01": 2.0}, {"R01": "retrieval"})
        with tempfile.TemporaryDirectory() as tmp:
            report_path = Path(tmp) / "report.json"
            base_path = Path(tmp) / "baseline.json"
            self._write(report_path, report)
            result = subprocess.run(
                [
                    sys.executable,
                    str(SCRIPT),
                    "--report",
                    str(report_path),
                    "--baseline",
                    str(base_path),
                    "--update",
                    "--note",
                    "unit test",
                ],
                capture_output=True,
                text=True,
            )
            self.assertEqual(result.returncode, cr.EXIT_OK)
            saved = json.loads(base_path.read_text(encoding="utf-8"))
            self.assertEqual(saved["llm_mode"], "mock")
            self.assertEqual(saved["note"], "unit test")
            self.assertEqual(saved["total"]["earned"], 2.0)
            # 剪枝后只有可比较字段，没有时间/地址/回答原文
            self.assertNotIn("generated_at", saved)
            self.assertNotIn("base_url", saved)
            self.assertEqual(set(saved["questions"][0]), {"id", "category", "points", "earned", "passed"})


if __name__ == "__main__":
    unittest.main()
