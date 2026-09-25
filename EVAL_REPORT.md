# EVAL_REPORT.md

公开题库的评测记录。全部为**无 LLM Key 的 mock 降级模式**实测，未配置任何模型 Key。

## 运行环境

- 服务：`starter/` 里的 FastAPI 服务，`python -m uvicorn kbqa.server:app --port <port>`。
- 评测：仓库根目录 `python eval/run_eval.py --base-url http://localhost:<port> --questions eval/public_questions.jsonl --out <dir>`。
- Python 3.13，无额外依赖（评测脚本只用标准库）。

## 三次得分

### 1. 作业原始 starter

- **commit**：`56f7a1f`（Moneki.ai 实操作业，未做任何修改）
- **复现方式**：`git worktree add ../moneki-starter-baseline 56f7a1f`，在其中建 venv、装依赖、`python -m kbqa.rebuild`、`python -m uvicorn kbqa.server:app --port 8002`。
- **运行命令**：
  ```bash
  python eval/run_eval.py --base-url http://localhost:8002 \
      --questions eval/public_questions.jsonl --out eval/reports/starter_original
  ```
- **关键配置**：无 Key（`llm_mode=mock`）；原始 starter 的清洗是空壳（`valid_sales_rows=18628`）、索引只有 25 篇文档。
- **总分**：**17.00 / 100**

| 类别 | 得分 | 满分 |
|---|---|---|
| metrics | 1 | 6 |
| retrieval | 6 | 15 |
| data | 0 | 12 |
| doc | 0 | 16 |
| version | 0 | 6 |
| hybrid | 0 | 18 |
| multi_turn | 1 | 9 |
| refusal | 6 | 8 |
| safety | 3 | 9 |
| health | 0 | 1 |

### 2. 第一关完成后的基线

- **commit**：`9e9c42a`（第一关：清洗、指标、看板完成后；RAG 未动）
- **运行命令**：
  ```bash
  python eval/run_eval.py --base-url http://localhost:8001 \
      --questions eval/public_questions.jsonl --out eval/reports/stage1_baseline
  ```
- **关键配置**：无 Key（mock）；`valid_sales_rows=18290`、`kb_docs=35`（清洗与索引装载已修正）。
- **总分**：**44.50 / 100**

| 类别 | 得分 | 满分 |
|---|---|---|
| metrics | 6 | 6 |
| retrieval | 8 | 15 |
| data | 12 | 12 |
| doc | 0 | 16 |
| version | 0 | 6 |
| hybrid | 3 | 18 |
| multi_turn | 3.5 | 9 |
| refusal | 8 | 8 |
| safety | 3 | 9 |
| health | 1 | 1 |

### 3. 第二关最终版本

- **commit**：`4eeafa6`
- **运行命令**：
  ```bash
  python eval/run_eval.py --base-url http://localhost:8001 \
      --questions eval/public_questions.jsonl --out eval/reports/stage2_final
  ```
- **关键配置**：无 Key（mock）；`valid_sales_rows=18290`、`kb_docs=35`、`kb_chunks=180`。
- **总分**：**100.00 / 100**

| 类别 | 得分 | 满分 |
|---|---|---|
| metrics | 6 | 6 |
| retrieval | 15 | 15 |
| data | 12 | 12 |
| doc | 16 | 16 |
| version | 6 | 6 |
| hybrid | 18 | 18 |
| multi_turn | 9 | 9 |
| refusal | 8 | 8 |
| safety | 9 | 9 |
| health | 1 | 1 |

### 4. 第三关前置加固后复测

在第二关最终版基础上加固了只读边界、证据体积、live 取证闸门、trace 可观察性（详见 `DEBUG_LOG.md` 分层 4 的 D12–D16），复测确认**没有回归**：

- **运行命令**：
  ```bash
  python eval/run_eval.py --base-url http://localhost:8001 \
      --questions eval/public_questions.jsonl --out eval/reports/stage3_prep
  ```
- **关键配置**：无 Key（mock）；`valid_sales_rows=18290`、`kb_docs=35`、`kb_chunks=180`、缓存键 `b0da151dbd8b`（与加固前一致——改动不影响真实知识库索引）。
- **总分**：**100.00 / 100**（分类得分与第 3 项完全相同）
- **同轮验证**：后端 `pytest` **108 passed**（新增只读闸门 / 证据上限 / live 取证 / trace / loader 共 5 个测试文件）；
  前端 `npm ci`（added 54 packages）+ `npm run build`（✓ built in 7.73s）通过。

## 仍未通过的题目

无。公开题库 55 题全部通过。

## 第三关边界加固后复测（mock 与 live 桩件分开报告）

本轮加固：live 数字提取与白名单来源、`run_sql` 内部对象与有界读取、超限结果保留业务值、
模型异常全路径 Key 脱敏（详见 `DEBUG_LOG.md` 分层 5 的 D17–D20）。

### 1. mock 模式（无 Key 降级）——公开评测

- **运行命令**：
  ```bash
  python eval/run_eval.py --base-url http://localhost:8001 \
      --questions eval/public_questions.jsonl --out eval/reports/stage3_boundary
  ```
- **关键配置**：无 Key（`llm_mode=mock`）；`valid_sales_rows=18290`、`kb_docs=35`、`kb_chunks=180`、缓存键 `b0da151dbd8b`。
- **总分**：**100.00 / 100**（55 题全绿，分类得分与第 3 项一致）——**无回归**。

### 2. live 桩件（不联网、不依赖真实 Key）——单元测试

| 专项 | 命令 | 结果 |
|---|---|---|
| 全部后端测试 | `pytest tests -q` | **140 passed** |
| live 取证与数字校验 | `pytest tests/test_live_evidence.py tests/test_llm_trace.py -q` | **28 passed** |
| 只读 / 内部对象 / 有界读取 | `pytest tests/test_tools_readonly.py -q` | **34 passed** |
| 前端（未改动，确认无回归） | `npm run build` | ✓ built in 7.70s |

其中 live 桩件覆盖的关键断言：中文紧贴数字（`是9999999元`）与负数/百分比被识别、`S02/P06/KB-013` 被排除；
“结果 100 + 回答 9999999”必须回退；“SQL 条件含 9999999、结果为 NULL”不放行；字段名/截断说明里的数字不放行；
超限结果保留业务标量并给出“请缩小查询范围”；非法 JSON 回显 Key 时 trace 与回答里都不出现 Key。

## 第三关完成后的最终验证

三关全部完成后（混合问答 live 编排 + 前端工作区 + 业务表白名单），复测结果如下。

### 1. mock 模式公开评测（无 Key 降级）

- **运行命令**：
  ```bash
  python eval/run_eval.py --base-url http://localhost:8001 \
      --questions eval/public_questions.jsonl --out eval/reports/stage3_final
  ```
- **关键配置**：无 Key（`llm_mode=mock`）；`valid_sales_rows=18290`、`kb_docs=35`、`kb_chunks=180`、缓存键 `b0da151dbd8b`。
- **总分**：**100.00 / 100**（55 题全绿）——live 编排、scope 校验、业务表白名单**没有造成回退**。

### 2. live 桩件与预检（不联网、不依赖真实 Key）

| 专项 | 命令 | 结果 |
|---|---|---|
| 全部后端测试 | `pytest tests -q` | **151 passed** |
| live 编排 + 数字取证 | `pytest tests/test_live_orchestration.py tests/test_live_evidence.py -q` | **29 passed** |
| 只读 / 内部对象 / 业务表 / 有界读取 | `pytest tests/test_tools_readonly.py -q` | **37 passed** |
| trace 脱敏 | `pytest tests/test_llm_trace.py -q` | **7 passed** |
| 前端 TypeScript 检查 + 构建 | `npm run build`（vue-tsc -b && vite build） | ✓ built in 7.82s |
| 模型接入预检 | `eval/llm_gateway.py preflight`（16 场景 P1–P14） | **13 PASS + 1 未检查**（P14，原因见 `LLM_SETUP.md` 第 7 节） |
| 换数据/文档重建验证 | worktree 临时副本：改一条金额 + 新增 KB-099 | 指标跟着变（8.00→999.00）、kb_docs 35→36、口径保持 18290、新文档检索命中第一、引用逐字、`run_sql` 白名单仍生效 |

### 3. 混合问答实测（mock 模式）

`618 当天 S02 牛肉poke 的活动目标是多少，实际卖了多少？` → `answer_type=hybrid`：
实绩来自真实 `query_metrics`（销量 125 / 净营业额 3625.00），目标值来自 KB-023 的逐字引用，
界面同屏展示两类证据（截图见 `docs/screenshots/assistant-hybrid.png`，完整流程见 `DEMO.md`）。

> **真实 live 未验证**：本机没有 DeepSeek Key，以上全部为预检（fake 模型）与单元桩件结果，
> 绝不把 mock 成绩写成 live。真实模型分数需配置 Key 后另跑。
> 说明：live 桩件用打桩替掉模型，验证的是**代码侧的取证闸门与脱敏**，不代表真实模型的回答质量；
> 真实模型分数需配置 Key 后另跑（见下方“关于 live 模式”）。

## 第四关：可调试性验收

第四关补齐 trace、调试面板、回归门禁、自拟题与演练。全部在 mock 模式实测，**不需要 Key、不请求付费模型**。

### 1. mock 公开评测与回归门禁

- 运行命令：
  ```bash
  python eval/run_eval.py --base-url http://127.0.0.1:8000 --questions eval/public_questions.jsonl
  python eval/check_regression.py --report report.json --baseline eval/baseline_mock.json
  ```
- **总分 100.00 / 100**（55 题全绿）；回归判定退出码 0。
- 基线 `eval/baseline_mock.json`：题库 `eval/public_questions.jsonl`、`llm_mode=mock`、55 题满分
  （只保留可比较的业务结果，去掉生成时间/地址/回答原文）。
- **门禁有效性实测**：把 `C01` 人为改成未通过 → 判定退出码 **1**，输出
  `[逐题] C01（doc）通过/得分退步（2.0 -> 0.0）；失败检查：citations；trace_id=t-20260901-0007`；
  恢复后退出码回到 0。

### 2. 后端测试与前端构建

- 后端 `pytest tests -q` → **167 passed**（新增 `tests/test_trace.py` 13 例、`tests/test_kb_drill.py` 2 例）。
- 前端 `npm run build` → 通过（vue-tsc 类型检查 + vite 构建）。
- 回归脚本自测 `cd eval/tests && python -m unittest test_check_regression -v` → **10 passed**。

> 这两个数字是**第四关当时**的状态，已被后面的验收修复轮推进：后端现为 **205 passed**、
> 回归脚本自测 **15 passed**。最新数字见下一节。

### 3. 自拟题（公开题未充分覆盖的风险）

```bash
python eval/run_eval.py --base-url http://127.0.0.1:8000 --questions eval/extra_questions.jsonl
```

- **25.00 / 25.00**（13 题全绿）。范围：问题改写（X01–X04）、追问隔离（X06）、
  时间歧义反问（X07）、无数据拒答（X08）、门店+闭区间精确值（X09）、
  经营数字 vs 周报估算（X10，`cite_none KB-050`）、历史版本（X11，引用 KB-010）、
  提示注入改写说法（X12/X13）。

### 4. 现场新增文档演练

```bash
cd starter && .venv/Scripts/python ../eval/drill_new_doc.py
```

- **11 / 11 PASS**：起服务（kb_docs=35）→ 停服务 → 加入 KB-099 → `python -m kbqa.rebuild` → 重启
  → `kb_docs 35→36`、`index_key b0da151dbd8b→f9b2ceda3da6` → `/api/retrieve` 命中 KB-099
  → `/api/chat` 引用 KB-099 → `/api/trace` 里能看到新命中。全程在临时副本，不碰正式知识库与索引缓存。
- 另在 `tests/test_kb_drill.py` 里做等价断言（新增文档后检索/问答/引用/trace 跟着变；
  替换数据后 metrics 取自新数据、口径仍 18290）。

## 第四关验收问题修复（本轮）

按优先级修的四个问题：Make 空值导出、演练索引隔离、trace 采纳语义、现场操作。
全部按"先拿红证、再改实现、后跑回归"的顺序做，逐条见 `DEBUG_LOG.md` 分层 9。

| 项 | 命令 | 结果 |
|---|---|---|
| 后端全量测试 | `pytest tests -q`（`MAKE_BIN=<便携版 make>`） | **205 passed** |
| 其中 Makefile 环境语义 | `pytest tests/test_makefile_env.py -q` | **6 passed**（**走真实 make 命令**，含两个真起服务的用例） |
| 其中 trace 采纳语义 | `pytest tests/test_trace_acceptance.py -q` | **9 passed** |
| 其中演练隔离 | `pytest tests/test_kb_drill.py -q` | **5 passed**（真跑一遍 drill 脚本再从外部核对） |
| 公开题库（mock，全量） | `run_eval.py --base-url http://127.0.0.1:8003 --questions eval/public_questions.jsonl` | **100.00 / 100.00**（55/55） |
| 回归门禁（全量严格） | `check_regression.py --report report.json` | 无回归，**退出码 0** |
| 回归门禁（局部） | `run_eval.py --only doc` → `check_regression.py --subset` | 局部 8 题通过、退出码 0，并打印"总分与分类分未比较" |
| 同一局部报告不加 `--subset` | `check_regression.py --report report.json` | 报 57 处假回归（总分 -84、缺题…），退出码 1 —— 说明为什么必须分开 |
| 自拟题 | `run_eval.py --questions eval/extra_questions.jsonl` | **25.00 / 25.00**（13 题全绿） |
| 新增文档演练 | `drill_new_doc.py` | **13 / 13 PASS**（kb_docs 相对 +1、索引键变化、检索/回答/引用/trace 命中、**跟踪索引 sha256 不变**） |
| 回归脚本自测 | `cd eval/tests && python -m unittest test_check_regression -v` | **15 passed** |
| 前端 | `npm ci` + `npm run build` | 通过（vue-tsc + vite） |

**Mock 成绩没有回退**：仍是无 Key 降级模式下的 55/55、100/100。

> 本机原本没装 make。为了按要求"用实际 Make 命令验证"，下载了 GNU Make 4.4.1 便携版
> （放在项目外的 `.tools/make/`，不入库），测试用 `MAKE_BIN=` 指过去；
> **CI 的 ubuntu runner 自带 make**，不设置也会跑这些用例。

## 关于 live 模式：三种状态分开报告

**不要把 mock 成绩写成 live。** 三者的实际状态如下：

| 状态 | 是什么 | 本次是否有结果 | 证据 |
|---|---|---|---|
| **mock（无 Key 降级）** | 不调模型，本地规划+检索+取数+模板作答 | **有**：公开题库 100/100、自拟题 25/25 | `eval/reports/stage3_final`、`eval/reports/extra` |
| **模型桩件 / 预检** | 用假模型或打桩替掉模型，验证**接线与代码侧闸门** | **有**：预检 13 PASS + 1 未检查（P14） | `LLM_SETUP.md` 第 7 节、`tests/test_live_*.py`、`tests/test_llm_trace.py` |
| **真实 live** | 连真实模型跑公开题库 | **未验证**：本机没有评审用的 DeepSeek Key | 见下 |

**真实 live 未验证**：本机从未对 `https://api.deepseek.com` 跑过公开评测，因此没有任何真实 live 分数。
预检的 **P14 是「未检查」，不是通过**（原因见 `LLM_SETUP.md` 第 7 节：预检的中性问题合成出的工具参数
被 Plan 范围校验拒绝，`normal`/`slow` 只产出 refusal，没有素材断言“保持连接没弄坏正文”）。

> 另记一次**非评审配置**的真实模型验证（StepFun `step-5-preview`，通过 `/step_plan/v1` 前缀接入）：
> 数据题、文档题、混合题、多轮追问均正确，并因此发现并修复了一个真 bug（问经营数字时不该引用周报估算，
> `4e7231e`）。这**不是** DeepSeek 的分数，只在 `AI_USAGE.md` 里作为过程记录。

第三关前置加固已把 live 的**取证闸门**（数字/引用只认本轮证据、检索内容去指令化、证据 ≤ 4096 字节）
与**可观察性**（完整模型请求与原始响应入 trace、Key 脱敏）做成 13 个打桩单元测试，
接入真 Key 后可直接复跑；`eval/llm_gateway.py preflight` 自检留待第三关接入时完成（见 `LLM_SETUP.md`）。
