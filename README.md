# Moneki.ai 经营分析系统

连锁餐饮品牌 Moneki.ai 的内部经营分析系统：经营看板 + （后续关卡的）AI 混合问答助手。
当前完成**第一关**：日期/门店筛选、营业额趋势、Top 10 商品、数据质量，以及契约规定的
`/api/metrics/summary` 与 `/api/metrics/daily`。

- 业务口径以知识库 **KB-001《指标口径手册 v3》** 为准（现行版，2026-05-01 起生效）。
- 系统的"今天"固定为 **2026-09-01**，与真实电脑日期无关。
- 作业原文（任务说明）保留在 `docs/ASSIGNMENT.md`，接口契约见 `docs/API_CONTRACT.md`。

## 快速开始（3 步）

需要 Python 3.12+ 和 Node.js 18+。

**第 1 步：装依赖**

```bash
cd starter
make setup                # 建虚拟环境并安装依赖
```

**第 2 步：重建清洗表与检索索引**

```bash
make rebuild              # 从 ../data 与 ../knowledge_base 重建
```

**第 3 步：启动后端与前端**

```bash
make run                  # 后端：http://localhost:8000（API 文档 /docs）
```

另开一个终端：

```bash
cd frontend
npm install
npm run dev               # 前端：http://localhost:5173，/api 自动代理到 8000
```

浏览器打开 **http://localhost:5173** 即可看到经营总览。

> Windows 下如果没装 make，等价命令：`python -m venv .venv` →
> `.venv\Scripts\pip install -r requirements.txt` →
> `.venv\Scripts\python -m kbqa.rebuild` →
> `.venv\Scripts\python -m uvicorn kbqa.server:app --port 8000`。
>
> 后端不在 8000 端口时，用 `VITE_API_TARGET=http://127.0.0.1:8001 npm run dev`
> 指定代理目标。

## 跑测试

```bash
cd starter
make test                 # 后端测试（140 个）：清洗口径、日期边界、清洗规则、分词/切块/安全、
                          # 只读 SQL 闸门、SQLite 内部对象、有界读取、证据体积、live 数字取证、
                          # trace 脱敏、loader doc_id 等
```

> `run_sql` 只接受单条只读查询（`SELECT`/`WITH … FROM`），并拒绝访问 `sqlite_master`/`sqlite_schema`/
> `pragma_*` 等内部对象；DataTools 的连接本身也是只读的（URI `mode=ro` + `PRAGMA query_only`）。
> 写入与 `ATTACH` 一律拒绝，见 `DEBUG_LOG.md` D12、D19。

## 跑公开评测

```bash
# 服务起在 8000（默认）后，在仓库根目录执行（只依赖 Python 标准库）：
python3 eval/run_eval.py --base-url http://localhost:8000 --questions eval/public_questions.jsonl

# 只跑某一类，调试更快：
python3 eval/run_eval.py --base-url http://localhost:8000 --questions eval/public_questions.jsonl --only retrieval
```

公开题库（无 Key 的 mock 降级模式）实测满分 100/100，分数与运行命令见 `EVAL_REPORT.md`；逐缺陷根因见 `DEBUG_LOG.md`。

## 架构

```
┌────────────┐   /api/*（Vite 代理）   ┌──────────────────────────┐
│  前端看板   │ ───────────────────────▶ │  FastAPI（starter/kbqa）  │
│ Vue3+TS    │                          │  server.py  参数校验/路由  │
│ Vite+ECharts│ ◀─────────────────────── │  service.py 组装/编排      │
└────────────┘       JSON               │  tools.py   指标查询       │
                                        │  sqlguard.py 只读 SQL 闸门 │
                                        │  cleaning.py 清洗（KB-001）│
                                        │  retriever/live 检索与问答 │
                                        └───────────┬──────────────┘
                                                    │ 只读（mode=ro）
                              ┌─────────────────────┴─────────────────┐
                              │ var/clean.db（清洗后）   .cache/index.json│
                              ▲                                       ▲
                        data/pos.db                        knowledge_base/
                     （原始 POS 导出）                        （35 篇文档）
```

- 前端不直接读 CSV/SQLite，所有数字都来自接口的真实查询。
- 数据库连接只读（`mode=ro` + `query_only`）；模型可调用的 `run_sql` 再过一层只读语法闸门，
  写入与 `ATTACH` 均被拒绝。
- 换数据或知识库后执行 `make rebuild`，页面展示的就是新结果；代码里没有写死任何数字。

![经营总览](docs/screenshots/dashboard.png)

## 技术选型

- **后端保留 starter 的 FastAPI**：契约接口都在这条服务上，评测脚本也按它来。
- **前端 Vue 3 + TypeScript + Vite + ECharts**：单页看板规模小，不需要后台模板；
  ECharts 用按需引入（LineChart + Grid + Tooltip），打包 gzip 约 190 KB。
- **清洗/指标纯 Python + SQLite**：数据量 1.8 万行，不需要额外引擎；金额以分（cents）
  为整数单位避免浮点误差，客单价四舍五入用 `ROUND_HALF_UP`。

## 口径与歧义的取舍

全部按 KB-001 v3（现行版）执行，不参考 v2 或交接文档：

| 点 | 取舍 | 依据 |
|---|---|---|
| 退款 | 计入净营业额（负数相减）；退款金额为绝对值单独展示 | v3 §4，v2 的"剔除退款行"已废止 |
| 有效订单数 | 销售行中不同 `order_id` 的个数，多行订单算 1 单 | v3 §4，v2 的"按明细行数"已废止 |
| 客单价 | 净营业额 ÷ 有效订单数，`ROUND_HALF_UP` 保留 2 位 | v3 §4 |
| 退款归属 | 按退款行自己的日期/门店/商品归属，不回溯原单 | v3 §4 / §7.4 |
| 金额为空 | 直接剔除，不按建档价回填 | v3 §3.2，v2 的回填已废止 |
| 日期格式 | `YYYY-MM-DD` / `YYYY/M/D` / `DD-MM-YYYY`（日在前）三种；`2026-13-45` 这类非真实日期判为无法解析 | v3 §2.2 |
| 重复行 | 七个字段规范化后完全一致才判重；共用订单号的不同商品行全部保留 | v3 §3.6 / §7.3 |
| 建档价 | 只做展示参考，金额一律以 `amount` 实收为准 | v3 §5.3 |
| 环比 | 未展示——没有做同口径的真实对比区间之前，不生成百分比 | 第一关要求 |

## 已知边界

- 数据质量区展示的是**本次重建的全量清洗统计**，不随日期/门店筛选变化（页面上有注明）。
- 筛选区间开始日期晚于结束日期时，前端禁用查询按钮并提示；接口本身对这类区间返回空数据。
- AI 问答（第二/三关）尚未实现，侧栏"AI 助手"为预留入口。
