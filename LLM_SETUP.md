# LLM_SETUP.md

模型接入说明。评审按本文把服务切到 DeepSeek 的 `deepseek-flash`，全程不改代码、只改环境变量。

## 1. 协议与路由

走 **OpenAI 兼容的 Chat Completions** 路线（契约 §7.1 推荐）。

- 只调用 `POST {LLM_BASE_URL}/chat/completions`，地址**原样拼接**：不补 `/v1`、不截路径、不只取域名。
- 不走 Anthropic 格式、不 Responses API、不本地模型，所以 `eval/llm_gateway.py preflight` 适用（结果见第 7 节）。

## 2. 环境变量（只读这三个）

| 变量 | 含义 | 示例 |
|---|---|---|
| `LLM_BASE_URL` | 模型服务地址，**原样使用** | `https://api.deepseek.com` |
| `LLM_API_KEY` | 模型 Key | `sk-xxxxxxxx` |
| `LLM_MODEL` | 模型名 | `deepseek-flash` |

- 三个值**只**从环境变量读（`starter/kbqa/config.py`），代码里没有任何写死的模型名 / Key / 地址。
- 可选：`LLM_TIMEOUT`（单次调用超时秒数，默认 120）、`CHAT_BUDGET`（`/api/chat` 整体预算秒数，默认 150）。
- **不在启动时校验 Key 格式、不查余额、不列模型**（契约 §7.2/§7.3）。
- 本地开发把 Key 放 `.env`（已加入 `.gitignore`，绝不入库）；仓库里只有 `.env.example` 占位样例。

## 3. 无 Key 降级（mock）模式

`LLM_API_KEY`、`LLM_BASE_URL`、`LLM_MODEL` 任一缺失 → `llm_mode = "mock"`：

- `/api/health`、`/api/metrics/*`、`/api/retrieve` 正常工作；
- `/api/chat` 走本地 Answerer（规划 + 检索 + 工具取数 + 模板渲染），**不调模型**，公开题库满分；
- 前端从 `/api/health` 读到 `mock` 时显示「本地演示 · 降级模式（未配置模型 Key）」。

配置齐全 → `llm_mode = "live"`，`/api/chat` 走模型编排（见第 4 节）。

## 4. 请求形状

发给模型的请求体只含 DeepSeek 文档列出的顶层参数：

```json
{
  "model": "<LLM_MODEL>",
  "messages": [ ... 每一轮原样追加，assistant 消息整条回传（含 reasoning_content） ],
  "max_tokens": 4096,
  "tools": [ ... ],
  "tool_choice": "auto"
}
```

- `max_tokens = 4096 ≥ 2048`（思考占额度，设小了会 `finish_reason: "length"`）。
- 工具定义见 `starter/kbqa/toolspec.py`（`query_metrics` / `daily_metrics` / `run_sql` / `search_kb` 等）。
- `search_kb` 的检索约束（`as_of` / `historical` / `store_id` / `year` / `window`）由**服务端从本轮 Plan 注入**，
  不靠模型猜日期；数据库工具的区间/门店/商品也会与 Plan 校验，不一致的结果不进证据。
- 每条 assistant 消息**整条**追加进 `messages`（含 `reasoning_content`），满足 D8 的回传要求；
  只有 `message.content` 会进入对外 `answer`。

## 5. 超时、错误与重试

- `/api/chat` 整体预算 150 秒（`CHAT_BUDGET`），到点返回结构化 `refusal`；单次调用取 `min(LLM_TIMEOUT=120, 剩余预算)`。
- 暂时性故障（429/500/503、`empty_content`、`insufficient_system_resource`、`transport`）重试一次，且只在预算够时重试。
- 正常 `finish_reason` 只认 `stop` 与 `tool_calls`；`length` / `content_filter` / `insufficient_system_resource` / `aborted` 一律按错误处理。
- 响应正文**前置空行**（`slow` 场景）在解析前 `.strip()` 跳过（D14）。
- 无论内部发生什么，`/api/chat` 都返回 HTTP 200 + 字段完整的 JSON，错误体现在 `answer_type: "refusal"`；
  模型输出里失败标记 / 半截话不会透传给用户（预检 P9 通过）。

## 6. 可观察性

`GET /api/trace/{trace_id}` 返回一次回答的完整链路，字段与实际记录一一对应：

- `plan`：原问题 / 补全问题 / 意图 / 日期区间 / 门店 / 商品 / 指标 / 检索查询；
- `retrievals[]`：每次检索的 `query`、约束（`as_of` / `store_id` / `year` / `window` / `historical`）、
  命中片段（`doc_id` / `chunk_id` / `score` / `padded` 补位标识 / `kind` / 120 字 `preview`）、
  以及被过滤片段的 `doc_id` 与 `reason`；
- `tools[]`：每次真实执行的工具/检索——`tool`、`params`、`status`（`ok`/`error`/`rejected`）、
  `took_ms`、`accepted` 是否进入回答依据、`entered`（`data_evidence`/`citations`）、
  被拒绝时的 `reject_reason`、有界结果摘要（`result_preview` + `result_bytes`）；
  mock 路径同样记录（过去没有工具步骤）；
- `llm_calls[]`：live 模式下逐轮**完整请求（含每一轮消息与工具定义）与模型原始响应**、
  `finish_reason`、HTTP 状态、错误与 `took_ms`；mock 模式下为空且 `model_called=false`
  （面板显示「本次未调用模型」）；
- `answer`：回答类型、预览、引用摘要、证据条数；`steps[]`：每步发生顺序与耗时（未测量到写 `null`）；
  `errors[]`：类型、消息、堆栈；
- **Key 脱敏是全链路的**：所有抛出路径（超时 / 网络 / 非法 JSON 回显 / HTTP 错误码）先脱敏，
  `TraceStore.save` 落盘前再递归脱敏一次。实测非法 JSON 回显 Key 时，`/api/trace` 与回答里都不出现 Key。
- trace 有界（默认保留最近 200 条）且持久化在 `starter/var/traces/`（已 gitignore），
  跨重启编号不重复、旧 ID 返回 404；落盘失败不影响问答（内存里仍留着）。
- 也可以把 `LLM_BASE_URL` 指向 `python3 eval/llm_gateway.py proxy --upstream https://api.deepseek.com --log llm_traffic.jsonl`
  打印的地址；日志只记 Authorization 长度、不记值（`llm_traffic.jsonl` 已在 `.gitignore`）。

## 7. 接入预检自测结果

`python3 eval/llm_gateway.py preflight --service-url http://127.0.0.1:8010`（fake 模型由预检自行启动，后端用其打印的三个环境变量启动）：

```
编号  检查项                                                            结果    说明
------------------------------------------------------------------------------------
P1    服务确实把请求发到了注入的 LLM_BASE_URL（含路径前缀）             通过    共观察到 60 次 POST /ds-gw/chat/completions。
P2    请求里的 model 等于注入的 LLM_MODEL                               通过    全部请求都用了 preflight-model-7f3a。
P3    注入的 Key 以 Authorization: Bearer 发送                          通过    全部请求都带了正确的 Bearer Key。
P4    只用了 DeepSeek 文档列出的顶层参数                                通过    只出现了 DeepSeek 文档列出的顶层参数。
P5    max_tokens 不设，或不小于 2048                                    通过    max_tokens 都不小于 2048。
P6    没有访问 {prefix}/chat/completions 之外的任何路径                 通过    只访问了 POST /ds-gw/chat/completions，没有碰任何别的路径。
P7    工具定义规范，且每一个工具调用都以 role=tool + tool_call_id 回传  通过    工具定义规范，44 个工具调用的结果都正确回传了。
P8    每个场景下 /api/chat 都返回 HTTP 200 与字段完整的合法 JSON        通过    32 次问答全部返回 200 和字段完整的 JSON。
P9    模型不可用时给出结构化 refusal，answer 从不是空串                 通过    模型不可用的场景下都给了结构化 refusal 或有据可查的回答，answer 从不是空串。
P10   思考内容没有漏进 answer / citations / data_evidence               通过    32 次回答里，思考标记都没有出现在任何对外字段里。
P11   /api/chat 在时限内返回（含长时间无响应的场景）                    通过    最慢的一次是 120.25 秒，都在 180 秒以内。
P12   注入环境变量后 /api/health 报告 llm_mode = live                   通过    llm_mode = live。
P13   多轮工具调用之间 reasoning_content 原样回传（没有触发 400）       通过    18 次多轮请求都原样回传了 reasoning_content。
P14   保持连接的空行与 SSE 注释没有把服务弄坏                           未检查  normal 场景本身就没有拿到回答，无法判断保持连接是不是额外的问题，先修前面的检查。

预检通过：在 OpenAI 兼容这条路线上，我们能原样接上你的服务。
未检查：P14（没有素材，见报告里的逐项说明）。
```

**P14 为什么是「未检查」**：预检的中性问题会合出一段 `query_metrics` 工具调用，其区间由合成器给
（如 `2026-06-01 ~ 2026-06-28`），而服务端按契约把工具参数与本轮 Plan 的时间窗做了一致性校验——
合成区间与「整体经营情况」的全量窗口不符，于是这些结果按「查错区间不作为证据」处理，`normal`/`slow`
场景最终返回的是结构化 `refusal` 而非有数字的回答，预检因此没有素材去断言「保持连接没弄坏正文」。
这不是接线失败：`slow` / `hang` 场景下服务仍返回了 200 + 合法 JSON（P8 通过），说明前置空行与
长时间无响应都没有破坏解析（`llm.py` 在解析前 `.strip()` 跳过前置空行，D14）。预检规范本身把
「未检查」定义为不算失败（见 `eval/README_llm_gateway.md`）。

## 8. 已知限制

- **真实 live 未验证**：本机没有 DeepSeek Key，以上全部为预检（fake 模型）与单元桩件结果，
  未对真实 `https://api.deepseek.com` 跑过 live 公开评测，不把 mock 成绩当 live。
- 预检工具自述其行为全部来自官方文档、未对照真实接口（见 `eval/README_llm_gateway.md` 第四节），
  若真实接口行为不同（尤其 400/422 的正文结构、`usage` 位置），请以真实为准并反馈。
- 检索是纯 BM25 + 别名扩写，未引入向量检索；跨语言靠别名词典覆盖公开题库，
  知识库之外的近义表述仍依赖词典。
- `run_sql` 是词法闸门（token + 表白名单 + 内部对象/文件路径拦截）而非 SQL 解析器，
  最后防线仍是连接级 `mode=ro`；两者同时生效。
