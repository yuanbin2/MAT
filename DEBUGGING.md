# DEBUGGING.md

现场 40 分钟调试手册。目标：**从一道失败题，走到一个可证伪的根因假设，再走到最小修复和回归确认**。

## 0. 准备（约 3 分钟）

```bash
cd starter
.venv/Scripts/python -m kbqa.rebuild                     # 重建清洗表与索引
.venv/Scripts/python -m uvicorn kbqa.server:app --port 8000   # 后端（无 Key = mock 降级）
cd ../frontend && npm run dev                             # 前端 http://localhost:5173
```

跑一遍评测并做回归判定（在仓库根目录）：

```bash
python eval/run_eval.py --base-url http://localhost:8000 --questions eval/public_questions.jsonl
python eval/check_regression.py --report report.json      # 非零退出 = 有题退步
```

判定脚本会直接给出**失败题号、类别、失败检查项、trace_id**。把 trace_id 复制下来。

## 1. 打开调试面板（约 1 分钟）

前端「AI 助手」页 → 右上角「**调试记录**」→ 粘贴 trace_id → 「查看」。
（也可以直接在对话里点某条回答下方的「查看调试记录」。）

面板按**排查顺序**分六段，从左到右就是一次回答的执行顺序：

| 段 | 先确认什么 |
|---|---|
| 概览 | 回答类型、模式（mock/live）、总耗时、错误数 |
| 问题理解 | 补全问题对不对；时间窗/门店/商品/指标识别对不对；检索查询是什么 |
| 知识库检索 | 命中的 doc_id/分数/片段预览、补位标识、被过滤的原因 |
| 工具与数据 | 每个工具的参数、结果、耗时、**是否进入回答依据**、拒绝原因 |
| 模型与异常 | live 的逐轮请求/原始响应；mock 显示「本次未调用模型」 |
| 时间线 | 每步发生顺序与耗时（缺失显示「未记录」） |

## 2. 按顺序排除（约 10 分钟）

1. **问题理解错了？** 如果 `问题理解` 里的时间窗、门店、商品与问题不符，先修规划（`planner.py`、`timeparse.py`），
   后面的检索与取数都会跟着错。
2. **没检索到？** 看 `知识库检索`：
   - `hits` 里没有该文档 → 装载/切块/分词问题（`loader.py`/`chunker.py`/`tokenizer.py`）；
   - 在 `filtered` 里被挡掉 → 版本/门店过滤问题（`retriever._eligible`），旁边写了原因；
   - 命中了但排在很后面 → 排序/加权问题（`retriever._multiplier`）。
3. **检索到了但没被引用？** `知识库检索` 是「检索到了」，`工具与数据`/`answer.citations` 才是「最终引用了」。
   两者不一致 → 取证逻辑（`answerer._doc_block` / `live._citations`）问题。
4. **数字不对？** 看 `工具与数据`：参数对不对（时间/门店/商品）、结果是真跑出来的还是被拒绝（`rejected` + `reject_reason`）。
   `accepted=false` 的绝不能当成证据。
5. **live 下模型乱来？** 看 `模型与异常`：请求里工具定义与提示词、原始响应、`finish_reason`、errors。
   mock 模式下这一段会明确显示「本次未调用模型」。

## 3. 写出可证伪的假设（约 5 分钟）

把「现象 → 假设 → **能推翻它的最小实验**」写下来，再动手。可复用的最小实验：

```python
# 检索是否命中
from kbqa.index import load_index; from kbqa.retriever import Retriever; from kbqa.config import load_settings
from datetime import date
s = load_settings(); idx = load_index(s.kb_dir, s.index_path, rebuild=True)
print([h.doc_id for h in Retriever(idx, date(2026,9,1)).search("你的问题", top_k=5).hits])

# 分词是否把中文切成了整句
from kbqa.tokenizer import tokenize; print(tokenize("外卖订单多久内可以申请退款"))

# 清洗是否按口径（保留行数、剔除分类）
from kbqa.tools import DataTools; print(DataTools(s.clean_db).cleaning_report())
```

## 4. 最小修复 + 回归（约 15 分钟）

```bash
cd starter
.venv/Scripts/python -m pytest tests -q                    # 全量后端测试
.venv/Scripts/python -m pytest tests/test_trace.py -q      # 只跑相关层
cd ..
python eval/run_eval.py --base-url http://localhost:8000 --questions eval/public_questions.jsonl --only doc
python eval/check_regression.py --report report.json       # 必须回到 0
```

**先加会红的测试，再改实现**（见 `DEBUG_LOG.md` 的分层记录）。改完重跑上面的两步，确认没有别的题被带崩。

## 5. 替换知识库 / 数据之后怎么刷新（约 5 分钟）

服务在启动时建索引；**改了 `knowledge_base/` 或 `data/` 必须重建并重启**：

```bash
# 1) 停掉服务（重建会重写 var/clean.db，服务正持有它，Windows 会锁文件）
# 2) 改 knowledge_base/ 或 data/
cd starter && .venv/Scripts/python -m kbqa.rebuild
# 3) 重启服务
.venv/Scripts/python -m uvicorn kbqa.server:app --port 8000
# 4) 确认索引真的变了：/api/health 的 kb_docs 与 index_key
```

一键复现整套「新增文档 → 重建 → 重启 → 检索/回答/引用/trace」：

```bash
cd starter && .venv/Scripts/python ../eval/drill_new_doc.py     # 11 项全 PASS
```

它在临时副本里做，不碰正式的 `knowledge_base/`、`data/` 与已跟踪的索引缓存。

## 6. 症状 → 先看哪里

| 症状 | 先看 trace 的哪一段 | 常见根因 |
|---|---|---|
| 数字整体偏大/偏小 | 工具与数据 | 闭区间末日被排除、退款没计入、订单数按行数算 |
| 某题查不到文档 | 知识库检索（hits 为空 / filtered 有它） | 装载丢了扩展名、切块丢尾、版本过滤过早、分词无交集 |
| 引用了不相干的句子 | 知识库检索 → answer.citations | 候选句排序方向、整篇文档当引用、命中了周报估算 |
| 回答里出现没查到的数字 | 工具与数据（accepted 状态） | 数字核验被绕过、白名单来源过宽 |
| live 回答被换成本地模板 | 模型与异常（errors） | 模型输出数字无依据、超时、`finish_reason` 异常 |
| trace 打不开 | 概览 / 面板状态 | trace 超出保留条数、ID 写错（面板会提示「不存在或已过期」） |
| 并发问答记录串了 | 概览（trace_id / question） | 不该出现的共享 `current_trace`（本项目没有，用参数传递） |

## 7. trace 的边界与安全

- 落盘在 `starter/var/traces/<trace_id>.json`（随 `var/` 被 gitignore），保留最近 200 条，超出按时间淘汰。
- 启动时扫描磁盘已有编号继续，**跨重启编号不重复**；内存没命中会回磁盘读，旧 ID 仍然 404。
- 落盘前统一过 Key 脱敏：真实 Key、`Bearer …`、`sk-…` 都会被擦掉；非法 JSON 回显 Key 的路径也有测试覆盖。
- 片段预览与工具结果都是**有界**的（片段 120 字、工具结果 400 字），不会把整份知识库塞进 trace。
