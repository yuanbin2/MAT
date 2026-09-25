# 已提交的评测逐题结果（脱敏）

这里放的是**真实模型（StepFun）最终那轮**公开/自拟题库的逐题评测结果，用于核对
`EVAL_REPORT.md` 里报告的 live 分数，而不是只看一个总分。

## 文件

- `stepfun-live-public-v6.json` —— 公开题库 55 题，**100.00 / 100.00**
- `stepfun-live-extra-v5.json` —— 自拟题库 13 题，**25.00 / 25.00**

## 元信息

| 项 | 值 |
|---|---|
| 模型 | `step-5-preview`（`https://api.stepfun.com/step_plan/v1`） |
| 代码提交 | `0cd3ab1` |
| 生成时间 | 见各文件 `generated_at` |
| 原始报告 | `eval/reports/stepfun_live_public_v6/report.json`、`stepfun_live_extra_v5/report.json`（该目录被 `.gitignore` 忽略） |

## 已脱敏（提交前机器闸门强制）

- **不包含任何 Key**：生成时对 `sk-` / `api_key` / `Bearer` / `secret` / `token`
  逐层扫描，命中即中断，绝不会落盘。
- **不含本地绝对路径与环境信息**：删掉了 `questions_file`、`kb_dir`、`base_url` 等
  指向本机 `E:\...` 的字段。
- **不含 trace 正文**：逐题里只留 `trace_id`（一个标识符），完整的模型请求/响应
  在 `starter/var/traces/`（未跟踪、不入库）。

## 字段说明

每个文件结构：

```
model, code_commit, generated_at
total        —— 总分 {earned, points, questions, passed}
per_category —— 各类别 {earned, points, passed, questions}
questions[]  —— 逐题 {id, category, points, earned, passed,
                      turns[]: {question, answer_type, passed, checks[], citations[], trace_id, answer}}
```

`checks[]` 里每一项是「检查名 + 是否通过 + 期望/实际/原因」，这就是核对 live 分数
最细的粒度——哪道题、哪个检查项、为什么，都能对上。
