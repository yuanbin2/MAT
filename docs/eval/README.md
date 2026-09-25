# 已提交的评测逐题结果（脱敏）

这里放的是**真实模型跑完整题库**的逐题评测结果，用于核对 `EVAL_REPORT.md` 里报告的
live 分数，而不是只看一个总分。当前两个模型：StepFun 与小米 MiMo。

## 文件

| 文件 | 模型 | 题库 | 成绩 |
|---|---|---|---|
| `stepfun-live-public-v6.json` | `step-5-preview` | 公开 55 题 | **100.00 / 100.00** |
| `stepfun-live-extra-v5.json` | `step-5-preview` | 自拟 13 题 | **25.00 / 25.00** |
| `mimo-live-public-v1.json` | `mimo-v2.5-pro` | 公开 55 题 | **98.00 / 100.00** |
| `mimo-live-extra-v1.json` | `mimo-v2.5-pro` | 自拟 13 题 | **23.00 / 25.00** |

## 元信息

| 项 | StepFun | MiMo |
|---|---|---|
| 模型 | `step-5-preview` | `mimo-v2.5-pro` |
| 接入 | OpenAI 兼容端点（地址不入库） | OpenAI 兼容端点（地址不入库） |
| 代码提交 | `0cd3ab1` | `ce37e1c` |
| 生成时间 | 见各文件 `generated_at` | 见各文件 `generated_at` |
| 原始报告 | `eval/reports/stepfun_live_public_v6/`、`stepfun_live_extra_v5/` | `eval/reports/mimo_live_public_v1/`、`mimo_live_extra_v1/` |

原始报告目录被 `.gitignore` 忽略，所以逐题结果从那里**脱敏后复制一份到这里**入库，
方便别人不跑模型也能核对分数。

## 已脱敏（提交前机器闸门强制）

- **不包含任何 Key**：生成时对 `sk-` / `api_key` / `Bearer` / `secret` / `token` / `tp-`
  等字样逐层扫描，命中即中断，绝不会落盘。
- **不含本地绝对路径与环境信息**：删掉了 `questions_file`、`kb_dir`、`base_url` 等
  指向本机 `E:\...` 或私有端点的字段。
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

### MiMo 失分题一览（对照 `checks[]` 可直接定位）

| 题号 | 类别 | 未通过检查 | 原因（`checks[].reason` 摘要） |
|---|---|---|---|
| `C04` | doc | `fact_all`、`cite_all` | 赔付金额 `CNY 8,600` 在 KB-022 第 6 块；本轮只检索到 KB-022 的 #1–#3，模型据此判断“没有记录”，改引 KB-021/KB-029 |
| `X07` | refusal | `answer_type_in` | 期望 `clarify`（“10 号”缺门店与月份上下文），模型自行按 2026-08-10 出数据答案 |

两题都是**模型行为差异**（检索深度不足 / 该追问时没追问），不是代码缺陷——
同一份代码下 StepFun 两题均通过。
