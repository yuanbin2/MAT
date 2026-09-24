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

## 仍未通过的题目

无。公开题库 55 题全部通过。

## 关于 live 模式

未配置真实 LLM Key，因此未提供 live 分数；以上分数即无 Key 降级模式的完整结果。模型可切换性与 `eval/llm_gateway.py preflight` 自检留待第三关接入时完成（见 `LLM_SETUP.md`）。
