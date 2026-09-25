# DEBUG_LOG.md

第二关：接手并修好 RAG 服务的逐缺陷记录。按数据流分层，每条包含现象、假设、验证、根因（文件与行）、修复 commit、回归测试与红绿证据。

基线（无 LLM Key 的 mock 降级模式）：

| 版本 | 命令 | commit | retrieval | doc | version | hybrid | multi_turn | safety | 总分 |
|---|---|---|---|---|---|---|---|---|---|
| 作业原始 starter | worktree 检出 `56f7a1f` 后跑 `run_eval.py --base-url :8002` | `56f7a1f` | 6/15 | 0/16 | 0/6 | 0/18 | 1/9 | 3/9 | **17.0** |
| 第一关完成后 | `run_eval.py --base-url :8001` | `9e9c42a` | 8/15 | 0/16 | 0/6 | 3/18 | 3.5/9 | 3/9 | **44.5** |
| 第二关最终 | `run_eval.py --base-url :8001` | `4eeafa6` | 15/15 | 16/16 | 6/6 | 18/18 | 9/9 | 9/9 | **100.0** |

> 所有分数都是无 Key 的 mock 模式实测，未配置任何 LLM Key。

---

## 分层 1：装载 / 切块 / 分词

### D1 中文整句被当成一个词，检索几乎无交集（根因）

- **现象**：公开检索题 R01/R04/R05/R06/R13/R15 的 `/api/retrieve` 返回 5 条全是 `score=0.0` 的 padded 补齐，没有任何真正命中；retrieval 类别 8/15。
- **假设**：先怀疑版本过滤把文档挡掉了；再怀疑索引没把文档装进去。用 `load_index` 直接看 `docs_meta`，发现 35 篇都在、片段也在，排除装载问题。
- **验证**：直接调用 `tokenize("外卖订单多久内可以申请退款")`，返回的是一个长字符串列表 `["外卖订单多久内可以申请退款"]`（按空格 split 的结果）。中文没有空格，所以整句成一个词元，与文档切出的词元永无交集。
- **根因**：`starter/kbqa/tokenizer.py` `tokenize()` 只做 `normalise(text).split()`。
- **修复**：改为英文单词/数字整体 + 连续中文切相邻二元组 + 单字保留（全角转半角、统一小写）；`TOKENIZER_VERSION` 递增使旧索引失效。commit `a794359`。
- **回归测试**：`tests/test_tokenizer.py::test_chinese_bigram` 等。修复前该测试对 `tokenize("三文鱼")` 期望 `["三文","文鱼"]`，旧实现返回 `["三文鱼"]`，红；修复后绿。

### D2 超过 300 字的文档末尾被切块丢掉

- **现象**：切块后片段数偏少（初始 53 段），怀疑长文档尾部丢失。
- **假设**：`chunker.py` 的切块区间没覆盖到结尾。
- **验证**：构造 301 字文档调用 `chunk_document`，`"".join(c.text)` 只有 300 字，末尾 1 字丢失。
- **根因**：`starter/kbqa/chunker.py` `range(0, len(text) - CHUNK_SIZE, CHUNK_SIZE)`，`len(text)-300` 的终点让最后不足一块的内容永远切不到。
- **修复**：改为 `range(0, len(block), CHUNK_SIZE)` 覆盖全文；顺带保留章节标题作 `heading` 上下文、识别 markdown 表格为 `kind="table"` 的整块（携带表头）。`CHUNKER_VERSION` 递增。commit `a794359`。
- **回归测试**：`tests/test_rag_layers.py::test_chunker_covers_tail`。修复前 301 字文档拼接后丢尾字，红；修复后绿。

### D3 HTML 文档带着标签入库，FAQ 检索被污染

- **现象**：R05（"发票怎么开"→ KB-061 FAQ.html）未命中，且 C05 的回答里出现了"首页 门店 菜单"等导航文字。
- **假设**：`.html` 的标签、`<script>`/`<style>` 被当作正文进了索引。
- **验证**：读 `load_index` 后 `index.texts["KB-061"]`，开头是 `<html>`、`<head>` 等原始标签，不是可见正文。
- **根因**：`starter/kbqa/loader.py` `load_document()` 的 html 分支只提取 `<title>`，`text` 仍是原始 HTML。
- **修复**：新增 `html_to_text()`（去 `<script>/<style>`、去标签、`html.unescape`），与评测脚本 `run_eval.py` 的逐字校验对齐。commit `a794359`。
- **红测证据**（检出 `a794359^` 的 worktree，对真实 KB-061 取正文）：
  `load_document(KB-061_常见问题FAQ.html).text` 以 `'<!DOCTYPE html>\r\n<html lang="zh-CN">\r\n<head>\r\n<meta charset="utf-8">…'` 开头——原始标签、`<meta>`、脚本都当正文进了索引。修复后同调用返回的是可见正文，不含 `<` `>` 标签。
- **回归测试**：`tests/test_loader_docid.py`（HTML 可见正文）+ 重建索引后 R05/C05 全绿。

### D4 元数据字段名写 `state`、读 `status`，版本过滤失效

- **现象**：R08（"现在单笔充值 500 送多少"→ 现行 KB-011）的 top-5 里，已废止的 KB-010（v1）排在第 1/2/3，现行 KB-011 才第 4；V01/V02/V03 全 0 分。
- **假设**：怀疑"已废止"的判断根本没生效。
- **验证**：在 `_eligible()` 里打印 `meta.get("status")`，恒为 `None`；而 `loader.meta()` 返回的字段叫 `"state"`。
- **根因**：`starter/kbqa/loader.py` `meta()` 写 `"state"`，而 `starter/kbqa/retriever.py::_eligible` 与 `docfacts.py::version_note` 读 `meta.get("status")`。
- **修复**：统一字段名为 `"status"`。commit `a794359`。
- **红测证据**（`a794359^` worktree）：`Document.meta()` 的键为
  `[doc_id, effective_from, estimates_only, filename, format, state, stores, stores_explicit, superseded_by, title, title_year, type, updated_at]`
  ——只有 `state`、没有 `status`。修复后键里是 `status`。
- **回归测试**：`tests/test_loader_docid.py::test_doc_id_comes_from_filename` 一族 + 公开题 R08 / V01–V03 全绿（修复前 R08 未命中、version 0/6）。

---

## 分层 2：召回 / 排序 / 版本

### D5 构造命中后重写 doc_id，编号与正文错配

- **现象**：R03 的 top-5 里同一篇 KB-062 出现两次、且有的 doc_id 对应的 `text` 明显不属于该文档。
- **假设**：命中对象在排序/去重后被人为改了 `doc_id`。
- **验证**：读 `retriever.search()`，看到 `hit.doc_id = ordered[len(hits)].doc_id` 这一行——`ordered` 是排序后的 chunk 序列，`len(hits)` 与 `adjusted` 的游标不再对齐（去重跳步后错位），于是 `text`（来自当前 position）与 `doc_id`（来自 ordered 的另一块）对不上。
- **根因**：`starter/kbqa/retriever.py` `search()` 内 `hit.doc_id = ordered[len(hits)].doc_id`。
- **修复**：删除该重写，`_hit()` 已从同一块 chunk 取 doc_id/chunk_id/text。commit `8f8054a`。
- **红测证据**（`8f8054a^` worktree，`search("退款 时限 外卖", top_k=5)`）：
  命中里出现 `('KB-013', 'KB-002#3')`、`('KB-013', 'KB-010#2')`——`doc_id` 是 KB-013，
  但 `chunk_id` 前缀来自 KB-002 / KB-010，编号与正文错配。修复后每条命中都满足
  `chunk_id.startswith(doc_id)`。
- **回归测试**：`tests/test_api.py::test_retrieve_ok` + 公开 R03 全绿。

### D6 版本过滤在取 top-k 之后，结果不足 top_k

- **现象**：部分检索题返回不足 5 条，违反契约 §4"恰好 top_k 条"。
- **假设**：被排除的文档先占用了名额，取完再删。
- **验证**：读 `search()`，`excluded` 文档的 chunk 仍在 `allowed` 里参与打分，最后才 `hits = [h for h in hits if h.doc_id not in excluded]`。
- **根因**：`starter/kbqa/retriever.py` `search()` 把版本/门店过滤放在取 top-k 之后。
- **修复**：先按 `excluded` 构建 `allowed`（排除这些文档的 chunk），打分与取 top-k 都在 `allowed` 上进行，删掉取完再过滤。commit `8f8054a`。
- **红测证据**（`8f8054a^` worktree）：`search("现在单笔充值 500 送多少", top_k=5)` 只返回 **4** 条
  （`filtered=3`）——已废止的文档先占了名额、取完再删，结果不足 top_k。修复后同一查询返回 5 条。
- **回归测试**：公开 15 道检索题 `results_count=5` 全部满足。

### D7 候选句升序排序，优先选最低分

- **现象**：C01–C08 的 doc 题 0 分，引用到的常常不是真正回答问题的句子。
- **假设**：候选句排序方向反了。
- **验证**：读 `_doc_block()`，`candidates.sort(key=lambda item: (round(item["score"], 2), item["effective_from"]))` 是默认升序，`candidates[0]` 是最低分。
- **根因**：`starter/kbqa/answerer.py::_doc_block` 排序缺 `reverse=True`。
- **修复**：改为按 `(score, effective_from)` 降序（分数高优先，分数接近时生效日期新者优先）。commit `8f8054a`。
- **红测证据**（`8f8054a^` worktree，对真实索引跑 `_candidates` 后套用旧排序表达式）：
  查询“退款规则”共 6 个候选，旧升序排序选中的是 `score=0.2575` 的那句
  （“- **净营业额** = 销售行金额之和 + 退款行金额之和。…”），而最高分是 `0.8305`
  （“- **退款行**：… `amount < 0` 的行。”）——确实优先选了最低分。修复后选中最高分。
- **回归测试**：公开 doc 题 C01–C08 全绿。

### D8 把整篇文档拼进 answer，超长 + 数字轰炸

- **现象**：doc 题 answer 里贴满整篇 OA 公文 / FAQ / 纪要，触发 `answer_length`、`number_flood`。
- **假设**：回答里被塞进了整篇文档正文。
- **验证**：`_answer_doc()` 返回 `self._context(result) + body`，`_context` 把命中文档的所有 chunk 拼起来。
- **根因**：`starter/kbqa/answerer.py::_context` 返回整篇文档。
- **修复**：`_context` 改为返回空串，只保留 `_doc_block` 逐字选取的短引用。commit `8f8054a`。
- **红测证据**（`8f8054a^` worktree）：直接调用旧 `Answerer._context(result)`，
  对单条命中返回 **201 字**（`chunks_of(doc_id)` 拼接的整篇正文）；修复后同调用返回 `""`。
- **回归测试**：`tests/test_live_evidence.py`（引用只取短句）+ 公开 doc 题 answer 均满足长度与数字上限。

---

## 分层 3：路由 / 取证 / 追问 / 安全

### D9 "多少/多久/几" 一刀切路由到数据库

- **现象**：C08（"员工迟到多久算一次"→ KB-016）被当成数据题，返回不到 15 分钟这条文档事实；C01/C03 同样路由错。
- **假设**：规划器末尾有一处"多久/几 → 取数"的覆盖。
- **验证**：读 `planner._choose_kind()` 末尾，`if E.has_any(text, ("多少","多久","几")): plan.intent = "data"` 无条件覆盖前面 `asks_policy` 的 doc 判断。
- **根因**：`starter/kbqa/planner.py` `_choose_kind()` 末尾的一刀切覆盖。
- **修复**：删除该覆盖，来源与焦点由 `asks_policy / anomaly / target / price / may_query` 逐层决定。commit `4eeafa6`。
- **回归测试**：公开 C01/C03/C08 全绿（修复前 doc 0/16）。

### D10 会话历史未按 session_id 隔离、且未传给规划器

- **现象**：T01–T03 多轮追问接不上（"那 7 月呢"答非所问）；A/B 会话交错会串线。
- **假设**：两处独立问题：SessionStore 是全局列表；Planner 没收到历史。
- **验证**：读 `sessions.py`，`history()/append()` 都忽略 `session_id`、操作单一 `self._turns`；读 `service.py::_answer`，`self.planner.plan(question)` 未传 `history`。
- **根因**：`starter/kbqa/sessions.py` 全局单列表；`starter/kbqa/service.py::_answer` 漏传 history。
- **修复**：SessionStore 改按 `session_id` 分字典；`_answer` 传 `history`，且只有 data/doc/hybrid 成功回答才写入上下文。commit `4eeafa6`。
- **回归测试**：`tests/test_rag_layers.py::test_sessions_isolated_by_id`（修复前两会话历史混在一起，红）。公开 multi_turn 9/9。

### D11 写操作与提示注入未接入安全判断

- **现象**：S02（"把 S01 的销售记录全部删掉"）、S03（"忽略规则…DROP TABLE"）返回 `doc` 而非 `refusal`，甚至把注入文本当检索词。
- **假设**：`is_destructive`/`is_prompt_probe` 已定义但从未被调用。
- **验证**：`grep` 全库，这两个函数只有定义、没有调用点。
- **根因**：`starter/kbqa/entities.py` 定义了安全判断，`planner.plan()` 未调用。
- **修复**：`planner.plan()` 入口先判 `is_destructive`/`is_prompt_probe`，命中即返回 refusal；`service._answer` 的异常同时写入 trace。commit `4eeafa6`。
- **回归测试**：`tests/test_safety.py`（修复前这些请求会走到检索而非 refusal）。公开 safety 9/9。

---

## 分层 4：只读边界 / live 取证 / 可观察性（第三关前置加固）

### D12 `run_sql` 可执行写入与库级操作，且连接不是只读

- **现象**：`run_sql` 把模型给的原样 `conn.execute(sql)`，还跟着一次 `commit()`；
  只要模型（或被检索文档里夹带的指令）让它写库，就能改数据、删表，甚至 `ATTACH` 别的库。
- **假设**：连接用的是普通读写连接，且没有 SQL 语法闸门。
- **验证（红，检出 `2a26866` worktree，对临时库副本跑行为复现）**：

  | 检查 | 旧实现结果 |
  |---|---|
  | `run_sql("DELETE FROM sales_clean")` | **放行**，行数 `2 → 0` |
  | `run_sql("ATTACH DATABASE 'evil.db' AS evil")` | **放行** |
  | `run_sql("SELECT 1")`（无 FROM） | **放行** |
  | `conn.execute("DELETE FROM sales_clean")` | **不抛错**，连接不是只读 |
  | `run_sql("SELECT * FROM big")`（1000×200 字符） | 结果 **11047 字节** |

  另外实测：即使把连接换成 `mode=ro`，SQLite **仍放行 `ATTACH`**，`PRAGMA query_only` 也挡不住——
  所以“只读连接”与“SQL 语法闸门”必须同时有，缺一不可。
- **根因**：`starter/kbqa/cleaning.py::open_readonly` 用普通 `sqlite3.connect`（可写）；
  `starter/kbqa/tools.py::run_sql` 无任何校验、且显式 `commit()`。
- **修复**：`open_readonly` 改用 URI `mode=ro` + `PRAGMA query_only=ON`；
  新增 `starter/kbqa/sqlguard.py::check_readonly_sql`（词法扫描，先抹掉注释/字符串/引号标识符），
  `run_sql` 只放行单条、以 SELECT/WITH 开头、带 FROM 的查询，其余在执行前返回结构化 `error`，不再 `commit()`。
- **回归测试**：`tests/test_tools_readonly.py`（DELETE/UPDATE/DROP/INSERT/CREATE/ALTER/PRAGMA/ATTACH/DETACH/VACUUM 共 10 条参数化；
  连接层只读；多语句/常量语句；词法不误伤）与 `tests/test_api.py::test_run_tool_rejects_writes_over_api`。
- **修复后**：同一批检查全绿——写入被拒且行数不变、`ATTACH` 被拒、常量语句被拒、连接层只读、结果 ≤ 4096 字节。

### D13 证据结果无体积上限，单条 `data_evidence.result` 可能超 4096 字节

- **现象**：契约硬上限要求单条 `data_evidence.result` 序列化后 ≤ 4096 字节；旧 `run_sql` 直接返回 `rows[:50]`
  （D12 红测里已见 11047 字节），其它工具输出也没有统一的体积闸门。
- **假设**：代码里没有任何字节级裁剪。
- **验证**：见 D12 最后一行——旧实现同一查询 11047 字节 > 4096。
- **根因**：`tools.py::run_sql` 只按行数截断；`answerer._call` / `service.run_tool` 直接把工具结果当证据。
- **修复**：新增 `sqlguard.fit_evidence()`（逐级降级：截行 → 截字段 → 退化成摘要）；
  `run_sql` 加 `MAX_SQL_ROWS=200`/`MAX_SQL_COLUMNS=40` 并对结果 `fit_evidence`；
  `service.run_tool` 与 `answerer._call` 对**所有**工具输出统一 `fit_evidence`；
  `live.LiveEngine` 入库证据前再压一次。
- **回归测试**：`tests/test_tools_readonly.py::test_row_limit_and_byte_limit` / `test_column_limit` / `test_fit_evidence_shrinks_oversized_result`；
  接口级 `tests/test_api.py::test_run_tool_evidence_within_contract_limit` / `test_chat_data_evidence_within_limit`；
  live 路径 `tests/test_live_evidence.py::test_live_evidence_result_capped`。

### D14 live 模式数字/引用取证过宽，且检索内容未去指令化就送进模型

- **现象**：模型回答里的数字只要在**整篇文档**、**问题原文**或**工具参数**里出现过就放行，等于给“蒙数字”开了口子；
  引用只要文档在索引里就认（哪怕本轮根本没检索到）；检索到的指令句原样进模型上下文。
- **假设**：`live._allowed_numbers` 把 `index.texts[doc_id]`（整篇）、`plan.question`、`plan.standalone`、`plan.window` 都并进白名单；
  `live._citations` 只校验 `doc_id in index.docs_meta`；`sanitize.py` 定义了却从没被调用。
- **验证（红，检出 `2a26866` worktree）**：
  - 数字只在**问题**里：回答“单笔充值满 500 送 500 元。”（无任何查询结果）→ 旧实现**直接放行**；
  - 数字只在**整篇文档**、该文档本轮未检索到：回答“单笔充值 500 送 60 元 [KB-100]。”→ 旧实现**放行**；
  - 引用**未检索到**的文档：回答“见 [KB-099]。”→ 旧 `citations=[{'doc_id': 'KB-099', 'quote': …}]`，**照收**。
- **根因**：`starter/kbqa/live.py::_allowed_numbers` / `_citations`；`sanitize.py::sanitize` 无调用点。
- **修复**：
  - `_allowed_numbers(evidence, retrieved_docs)` 只从**本轮**的证据结果与本轮检索片段取数，
    删掉整篇文档/问题/参数来源；日期类写法由 `_numbers_in` 直接剔除、不再需要白名单；
  - `_citations` 只认本轮 `search_kb` 真正返回过的 `doc_id`，引用句从**检索到的片段**里挑；
  - 新增 `_clean_kb_result`：检索结果先 `sanitize` 去掉指令句，再进模型上下文，并写 `trace.step("kb_instruction_stripped")`。
- **回归测试**：`tests/test_live_evidence.py`（`test_citation_only_from_retrieved_documents`、
  `test_number_only_in_question_is_not_enough`、`test_number_only_in_whole_document_is_not_enough`、
  `test_instruction_like_kb_text_is_stripped` 等 10 例）。

### D15 loader 的 `doc_id` 取元数据而非文件名

- **现象**：文件名叫 `KB-042_…`、YAML 头却写 `doc_id: KB-999` 时，入库编号跟着 YAML 走，
  与契约 §0“文件名开头的 KB-xxx 就是 doc_id”不符；冲突也不告警，静默以元数据为准。
- **假设**：`doc_id = meta.get("doc_id") or filename`，元数据优先。
- **验证（红，`2a26866` worktree）**：对 `KB-042_通知.md`（头里 `doc_id: KB-999`）调用 `load_document`，
  旧实现返回 `doc_id=KB-999`，且 `warnings` 为空——既取错又不告警。
- **根因**：`starter/kbqa/loader.py::load_document` 的 doc_id 取值顺序。
- **修复**：`doc_id` 一律取文件名开头的 `KB-\d+`；文件名没有编号的直接跳过；
  `meta.doc_id` 与文件名不一致时追加告警并说明“以文件名为准”。
- **回归测试**：`tests/test_loader_docid.py`（文件名优先、冲突告警、无前缀跳过、
  仅 YAML 有编号也不认、重复编号告警）。
- **修复后**：同调用返回 `doc_id=KB-042`，`warnings` 含“元数据 doc_id=KB-999 与文件名 … 不一致，已以文件名为准”。

### D16 trace 只留了提示词预览，没有完整请求与原始响应

- **现象**：契约 §6 要求 trace 里能看到“发给大模型的最终提示词和模型原始输出”，§7.2 更要求能看到
  “完整请求，包括提示词、工具定义和每一轮的消息”。旧记录只有 `prompt`（4000 字预览）、
  工具定义只记了**个数**、也没有原始响应全文。
- **假设**：`llm.LLMClient.chat` 的记录字段过窄。
- **验证（红，`2a26866` worktree 代码走查 + 本机打桩实测）**：旧记录字段为
  `endpoint/model/messages(计数)/tools(计数)/prompt(预览)/finish_reason/content_chars/tool_calls(名字)/raw_content(预览)/raw_reasoning(预览)/usage`
  ——没有 `request`（完整 body）、没有 `response`（原始响应）。
- **根因**：`starter/kbqa/llm.py` 只存 `_preview(...)` 的摘要。
- **修复**：新增 `request`（完整 body：每一轮 `messages` + 完整 `tools` 定义 + `max_tokens`）与
  `response`（模型原始响应全文）两个字段，仅做**密钥脱敏**、不截断内容；
  脱敏用 `_mask`（替换真实 Key + `Bearer ***` + `sk-***` 正则），Key 本身从不放进 body。
- **回归测试**：`tests/test_llm_trace.py`（完整请求可原样解析回 `messages`/`tools`；
  完整响应含 `reasoning_content`；401 错误的 `detail` 也脱敏；trace 里不含 Key 与 Authorization）。
- **修复后**：`record["request"]` 可 `json.loads` 还原出完整 `messages` 与 `tools`，`record["response"]` 等于原始响应文本，
  且 `SECRET not in json.dumps(record)`。

---

## 分层 5：第三关边界加固（数字提取 / 内部对象 / 有界读取 / 异常脱敏）

### D17 数字提取漏识别“中文紧贴数字”与负数

- **现象**：回答里“净营业额是9999999元”这种写法，中文紧贴数字时数字**根本没被提取**，
  于是“数字是否造假”的校验被整段跳过——等于没有校验。
- **假设**：判断“数字是否紧贴编号”用了 `str.isalnum()`；而 Python 里汉字
  `"是".isalnum()` 也是 `True`，所以中文前一位也被当成“编号的一部分”跳过了。
- **验证（红，检出 `6512abe` worktree）**：`_numbers_in("净营业额是9999999元")` → `[]`；
  `_numbers_in("退款是-500元")` → `[]`。同时 `S02`/`P06`/`KB-013` 的排除是**正确**的（`[]`）。
- **根因**：`starter/kbqa/live.py::_numbers_in` 用 `cleaned[start-1].isalnum()` 判定紧贴。
- **修复**：紧贴判断只按 **ASCII** 字母/数字/下划线（`S02`/`P06`/`KB-013` 仍被排除），
  中文紧贴照常识别；数字正则支持半角/全角负号（`-500`、`－500`）与百分比（`25.3%`）。
- **回归测试**：`tests/test_live_evidence.py`（`test_numbers_chinese_adjacent_are_recognized`、
  `test_numbers_negative_are_recognized`、`test_numbers_percentage_are_recognized`、
  `test_identifier_numbers_are_excluded`、`test_date_like_tokens_are_ignored`）。
- **题目要求的回归**：`test_regression_result_100_must_reject_answer_9999999`——
  证据只有 `net_revenue=100`、回答写“净营业额是9999999元” → 必须回退模板回答（红测里旧实现**直接放行**）。

### D18 数字白名单来源过宽：从 SQL 文本、入参、字段名、截断说明取数

- **现象**：白名单是把整个 evidence 项 `json.dumps` 后取数，于是 `params`（入参）、
  `result.sql`（SQL 原文）、`result.columns`（字段名）、`result.note`（截断说明里的字节数）
  里的数字都被当成“可放行”——模型把 SQL 条件里的数字搬进回答就能过。
- **假设**：`_allowed_numbers` 用 `_numbers_in(json.dumps(item))`，没有区分“数据值”与“元信息”。
- **验证（红，`6512abe` worktree）**：
  - SQL 条件含 9999999、查询结果为 `NULL`：回答“净营业额是9999999元” → 旧实现**放行**；
  - 字段名 `total_9999999` / 截断说明 `bytes_before=8888888`：回答对应数字 → 旧实现**放行**。
- **根因**：`starter/kbqa/live.py::_allowed_numbers` 的取数来源。
- **修复**：白名单只读 `evidence[i]["result"]` 的**数据值**（`_data_numbers` 递归取值、跳过字典键），
  并跳过元信息键 `EVIDENCE_META_KEYS = {sql, columns, keys, note, bytes_before, truncated}`；
  入参 `params` 完全不参与取数。
- **回归测试**：`test_whitelist_ignores_sql_text_and_params`（含题目要求的
  “SQL 条件含 9999999、结果为 NULL”用例）、`test_whitelist_ignores_column_names_and_notes`、
  `test_whitelist_uses_actual_result_values`、`test_whitelist_reads_retrieved_chunks_only`。

### D19 `run_sql` 可访问 SQLite 内部对象；结果集无界读取；超限只剩字节数摘要

- **现象**：三处边界都不够严：
  1. `SELECT name FROM sqlite_master`、`SELECT * FROM pragma_table_info(...)` 可以拿到库内部结构；
  2. `run_sql` 用 `cursor.fetchall()` 把**整个结果集**读进内存再截断；
  3. `fit_evidence` 超限时退化成 `{"note":…, "keys":…, "bytes_before":N}`——
     只剩字节数，业务值全丢，等于“没有证据”。
- **假设**：闸门只查了写操作；读取用 `fetchall`；压缩兜底没有保住标量业务值。
- **验证（红，`6512abe` worktree）**：
  - `run_sql("SELECT name FROM sqlite_master")` → **放行**（返回库结构）；
  - `run_sql("SELECT * FROM pragma_table_info('t')")` → **放行**；
  - 对 `{"net_revenue":162414.0, "orders":4446, "rows":[…超长…]}` 调 `fit_evidence`
    → 返回 `keys=['bytes_before','keys','note']`、`net_revenue=None`（业务值丢失）；
  - `grep -n "fetchall\|fetchmany" tools.py` → 旧第 105 行是 `cursor.fetchall()`（无界读取）。
- **根因**：`sqlguard.check_readonly_sql` 缺内部对象检查；`tools.run_sql` 用 `fetchall`；
  `sqlguard.fit_evidence` 的兜底摘要只有元信息。
- **修复**：
  1. `check_readonly_sql` 增加 `internal_objects()`：在“去掉引号”的原文上扫 `sqlite_*` / `pragma_*`
     （补上词法骨架会抹掉带引号标识符的盲区），命中即拒绝；
  2. `run_sql` 改 `cursor.fetchmany(MAX_SQL_ROWS + 1)` **有界读取**，并回报 `columns_total`；
  3. `fit_evidence` 逐级降级但**始终保住标量业务值**（截行 → 截字段 → 丢明细留标量 →
     只留数值标量），并附带明确的“请缩小查询范围（收窄日期/门店/商品或减少返回字段）”，
     **不再返回只有字节数的摘要**。
- **回归测试**：`tests/test_tools_readonly.py`（`test_internal_objects_rejected` 7 条参数化、
  `test_internal_object_check_catches_quoted_names`、`test_business_queries_still_allowed`、
  `test_run_sql_reads_bounded_rows`、`test_fit_evidence_preserves_business_scalars`、
  `test_fit_evidence_never_returns_bytes_only_summary`、`test_oversized_run_sql_keeps_scalars_and_asks_to_narrow`）
  与接口级 `tests/test_api.py::test_run_tool_rejects_internal_objects_over_api`。

### D20 模型异常路径未脱敏：非法 JSON 回显 Key 会写进 trace

- **现象**：响应不是合法 JSON 时，异常信息写的是**原始响应正文**；如果模型/网关把 Key
  回显在正文里（调试信息、错误页），Key 会经由 `LLMError.detail` → `trace.step("answer_live_failed")`
  与 `trace.errors` 落进 `/api/trace`（此前只对 `record["detail"]` 做了脱敏，异常这条路径漏了）。
- **假设**：脱敏只覆盖了 trace 记录字段，没有覆盖抛出的异常信息，也没有落盘前的统一闸门。
- **验证（红，`6512abe` worktree，端到端跑 Service）**：
  `Service.chat` 在 live 模式下抛 `LLMError("bad_json", …含 Key…)`：
  `/api/trace` 里出现 Key = **True**，泄漏位置 `['answer_live_failed', 'response']` 且 `errors` 也含 Key。
  单测层面：`SECRET in str(exc)` = **True**（旧实现）。
- **根因**：`starter/kbqa/llm.py` 的 `bad_json`/`timeout`/`transport` 分支抛出原始正文；
  `starter/kbqa/trace.py::TraceStore.save` 没有脱敏入口。
- **修复**：
  1. 抽出公共 `llm.redact_secret(text, secret)`（替换真实 Key + `Bearer ***` + `sk-***` 正则），
     `_mask` 委托它，**所有**抛出路径（超时/网络/非法 JSON/HTTP 错误码）都先脱敏；
  2. `TraceStore.save(trace, redactor=...)` 增加落盘前的统一闸门；
  3. `Service` 用 `_redact_payload` 递归脱敏整份 trace 后落盘，并在捕获 `LLMError` 时再次脱敏 `detail`。
- **回归测试**：`tests/test_llm_trace.py`（`test_bad_json_echoing_key_is_masked`、
  `test_timeout_and_transport_details_are_masked`、`test_trace_store_redacts_on_save`、
  `test_service_trace_masks_key_on_llm_error` 端到端）。
  修复后端到端断言：`/api/trace` 与回答里都不含 Key，同时错误仍在 trace 里可见（可观察性不因脱敏丢失）。

---

## 分层 6：第三关边界加固（预防性）

> 这一层的各项是**为第三关主动补的边界**，不是线上事故驱动的缺陷修复；
> 每项都有新测试，红测证据只对实际跑过 worktree 复现的项声称，其余如实标注。

### D21 `run_sql` 没有业务表白名单，任意表都能读

- **现象（预防性）**：词法闸门只拦写操作与 `sqlite_*`/`pragma_*`，`SELECT * FROM secrets`
  这类**业务表之外**的表照样放行——第三关把 `run_sql` 暴露给模型后，这是不必要的暴露面。
- **红测证据**（检出 `f37cda1` worktree）：`check_readonly_sql("SELECT * FROM secrets")` → `[]`；
  `check_readonly_sql('SELECT * FROM "other_db"')` → `[]`。
- **修复**：新增 `BUSINESS_TABLES = {sales_clean, stores, products}`；`referenced_tables()` 从
  `FROM`/`JOIN` 后取表名（先剥字符串字面量与注释、再去引号），`cte_names()` 认 `WITH` 里的 CTE；
  访问白名单之外的表一律拒绝，业务查询与 CTE 不受影响。
- **回归测试**：`test_unknown_table_rejected`、`test_cte_over_business_tables_allowed`、
  `test_business_queries_still_allowed`；接口级 `test_run_tool_rejects_internal_objects_over_api`。

### D22 数据库文件路径 / 扩展加载没有专门拦截（belt-and-suspenders）

- **说明**：`SELECT load_extension('/tmp/x.so')` 这类**没有 FROM** 的语句本来就会被
  “没有 FROM”规则拒绝；`ATTACH DATABASE 'file:...'` 也已被 `ATTACH` 关键字拒绝。
  新增的 `file_path_objects()` 是在这两层之上的第三道保险：即使未来有人放宽 FROM 检查
  或写出形如 `SELECT * FROM sales_clean WHERE path = 'file:...'` 的查询，
  `file:` 路径、`load_extension`、`readfile`/`writefile`/`edit` 也会被显式拒绝。
  此项**没有单独的 worktree 红测**（旧行为是被前两层部分覆盖的），如实标注为加固而非缺陷修复。
- **回归测试**：`test_file_path_and_extension_rejected`。

### D23 `search_kb` 未继承 Plan 检索约束；数据库工具参数未与 Plan 校验（第三关新要求）

- **背景**：第三关要求“模型调用 search_kb 时必须继承本轮 Plan 的 as_of/historical/store_id/year/window，
  复用 /api/retrieve 背后的同一套 retriever”，并且“模型查了错误月份或错误门店的结果不能当证据”。
  这是新能力，不是修复某个已发生的缺陷。
- **实现**：`live._search_kb()` 用 `answerer.retriever`（即 `/api/retrieve` 同一套）并注入 Plan 约束；
  `live._scope_error()` 在工具执行后校验区间/门店/商品，不符则结果不进证据并记 `tool_scope_mismatch`。
  Plan 以参数传递，不进任何可被并发覆盖的全局变量。
- **回归测试**：`tests/test_live_orchestration.py`（约束继承、as_of 由 Plan 决定、门店/窗口/比较窗口
  一致性、端到端“查错区间的结果不进证据”）；`tests/test_live_evidence.py::test_doc_target_value_allowed_but_fabricated_actual_rejected`
  覆盖“政策目标值来自文档、经营实绩来自数据库”的区分。

---

## 分层 7：第四关可调试性（承接 D16，补全而非新缺陷）

> 这一层是**补全上一轮的 trace 范围**，不是新发现的线上缺陷。红测证据只对实际跑过的部分声称，
> 代码走查得到的部分如实标注。

### D24 mock 路径的工具调用没有进 trace；live 的工具步骤只有参数没有结果

- **现象（承接 D16）**：D16 给 trace 补了「完整模型请求/响应」，但**工具侧不完整**：
  `Answerer._call` 有 `evidence`、没有 `trace` 参数，mock 路径的步骤只有
  `plan / search / answer_mock / response`，**看不到任何工具调用**；live 的 `trace.step("tool", …)`
  只写 `{tool, params}`，**没有结果、没有耗时、没有是否采纳**。
- **验证（代码走查）**：`grep -rn "_call(" starter/kbqa/` 时 `Answerer._call(self, evidence, name, **params)`
  签名里没有 trace；`live.py` 的 `trace.step("tool", {"tool": name, "params": params}, started=started)`
  没有把 result 写进去。
- **修复**：`_call(self, evidence, name, trace=None, **params)` 记录工具步骤（工具名/最终参数/有界结果摘要/
  耗时/`accepted=True`/`entered="data_evidence"`），14 个调用点补 `trace=trace`
  （`hybrid._zero_days`/`_baseline` 顺带加上 trace 形参）；live 的工具步骤改为
  `trace.tool(...)`，区分 `ok`/`error`/`rejected`，拒绝时带 `reject_reason`、**绝不标成已采纳**。
- **回归测试**：`tests/test_trace.py::test_mock_chat_trace_has_real_tool_steps`
  （断言 mock 也有工具步骤、有 `result_preview`/`took_ms`/`entered`）、
  `test_live_orchestration.py::test_wrong_scope_tool_result_not_used_as_evidence`
  （断言被拒绝的调用 `status=rejected`、`accepted=False`、带原因）。

### D25 TraceStore 只在进程内、编号跨重启会重复

- **现象**：旧 `TraceStore` 只保留进程内最多 200 条，编号是 `t-{业务日期}-{进程内计数}`；
  重启后计数从 1 重新开始，**新记录会复用旧编号**，且重启前的记录再也找不回来（现场调试要复现失败题就断了）。
- **验证（代码走查）**：`TraceStore.__init__` 只有 `self._counter = 0`，没有读磁盘；
  `new_id` 直接 `self._counter += 1`。
- **修复**：`TraceStore(capacity, directory)` 落盘 `var/traces/<trace_id>.json`；启动时扫磁盘已有编号
  把计数推到最大值，`new_id` 循环到未用过的编号；内存未命中回磁盘读；启动与每次写入后按容量剪枝；
  落盘失败不影响问答。`Settings.traces_dir` 跟着 `var/` 一起被 gitignore。
- **回归测试**：`tests/test_trace.py`（跨重启按 ID 找回、重启后编号不重复、容量上限、
  启动剪枝、落盘无 Key、旧 ID 404）。

### D26 没有回归门禁：`run_eval.py` 失分也返回 0

- **现象**：评测脚本写完 `report.json` 就返回 0，CI 拿不到“有没有退步”的信号。
- **验证**：`grep -n "sys.exit\|return 0\|returncode" eval/run_eval.py`——正常跑完不按得分退出。
- **修复**：新增 `eval/check_regression.py` 对比跟踪的 mock 基线（`eval/baseline_mock.json`），
  比较总分/分类/逐题通过状态，退步或漏题或坏报告 → 非零退出，并输出题号、类别、失败检查项与 trace_id；
  `.github/workflows/ci.yml` 串起测试 → 重建 → 起服务 → 评测 → 回归判定 → 前端构建。
- **有效性实测（不是嘴上说）**：把 `C01` 的成绩人为改低 → 退出码 1 且报出
  `[逐题] C01（doc）…失败检查：citations；trace_id=t-20260901-0007`；恢复后退出码 0。
- **回归测试**：`eval/tests/test_check_regression.py`（分数下降/漏题/分类退步/坏报告/缺键 →
  非零；无变化与新增题 → 0；CLI 退出码；`--update` 剪枝）。

### D27 新增文档演练暴露的顺序问题：重建与服务抢 clean.db

- **现象**：演练脚本先起服务、再改文档、再 `kbqa.rebuild`，重建报
  `PermissionError: [WinError 32] 另一个程序正在使用此文件: …\var\clean.db`（服务持有 SQLite 连接）。
- **验证**：演练脚本第一次运行输出 `FAIL kbqa.rebuild 退出码=1`，堆栈指向 `cleaning.build_clean_db`
  的 `target.unlink()`。
- **修复**：演练流程改为「起服务确认基线 → **停服务** → 加文档 → 重建 → 重启 → 验证」，
  并把这一步写进 `DEBUGGING.md` 第 5 节。
- **修复后**：演练 **11/11 PASS**（kb_docs 35→36、index_key 变化、retrieve/chat/trace 都能定位新文档）。

---

## 尚未解决 / 已知边界

- 无 LLM Key 的 mock 降级模式已满分；live 模式（配置真实模型后）未在本机对真实 API 跑过，
  `LLM_SETUP.md` 与 `eval/llm_gateway.py preflight` 留待第三关接入时完成。
  本轮已把 live 的**取证闸门**（数字/引用白名单、检索去指令化、证据体积）与**可观察性**
  （完整请求/响应入 trace、Key 脱敏）用打桩做成了 13 个单元测试，接入真 Key 后可直接复跑。
- 检索为纯 BM25 + 别名扩写，未引入向量检索；跨语言靠别名表的 distinctive token（如 `salmon`→三文鱼poke），
  覆盖了公开题库，但对知识库之外的近义表述仍依赖词典。
- `run_sql` 是词法闸门而非 SQL 解析器：它按 token 判定（已排除注释/字符串误伤）并额外拦住
  `sqlite_*`/`pragma_*` 内部对象，但真正的最后防线仍是连接层的 `mode=ro`——两者同时生效，任一层单独都不足。
- live 的“数字必须来自真实查询”是**面向数值的白名单**：日期类写法与编号（S02/P06/KB-013）不参与校验，
  因此日期本身不需要证据支撑；这是一处有意的取舍，不是漏洞。
