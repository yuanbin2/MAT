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
- **回归测试**：`tests/test_rag_layers.py` 通过重建后的索引 + R05/C05 全绿间接覆盖。

### D4 元数据字段名写 `state`、读 `status`，版本过滤失效

- **现象**：R08（"现在单笔充值 500 送多少"→ 现行 KB-011）的 top-5 里，已废止的 KB-010（v1）排在第 1/2/3，现行 KB-011 才第 4；V01/V02/V03 全 0 分。
- **假设**：怀疑"已废止"的判断根本没生效。
- **验证**：在 `_eligible()` 里打印 `meta.get("status")`，恒为 `None`；而 `loader.meta()` 返回的字段叫 `"state"`。
- **根因**：`starter/kbqa/loader.py` `meta()` 写 `"state"`，而 `starter/kbqa/retriever.py::_eligible` 与 `docfacts.py::version_note` 读 `meta.get("status")`。
- **修复**：统一字段名为 `"status"`。commit `a794359`。
- **回归测试**：公开题 R08 / V01–V03 全绿（修复前 R08 未命中、version 0/6）。

---

## 分层 2：召回 / 排序 / 版本

### D5 构造命中后重写 doc_id，编号与正文错配

- **现象**：R03 的 top-5 里同一篇 KB-062 出现两次、且有的 doc_id 对应的 `text` 明显不属于该文档。
- **假设**：命中对象在排序/去重后被人为改了 `doc_id`。
- **验证**：读 `retriever.search()`，看到 `hit.doc_id = ordered[len(hits)].doc_id` 这一行——`ordered` 是排序后的 chunk 序列，`len(hits)` 与 `adjusted` 的游标不再对齐（去重跳步后错位），于是 `text`（来自当前 position）与 `doc_id`（来自 ordered 的另一块）对不上。
- **根因**：`starter/kbqa/retriever.py` `search()` 内 `hit.doc_id = ordered[len(hits)].doc_id`。
- **修复**：删除该重写，`_hit()` 已从同一块 chunk 取 doc_id/chunk_id/text。commit `8f8054a`。
- **回归测试**：`tests/test_api.py::test_retrieve_ok` + 公开 R03 全绿。

### D6 版本过滤在取 top-k 之后，结果不足 top_k

- **现象**：部分检索题返回不足 5 条，违反契约 §4"恰好 top_k 条"。
- **假设**：被排除的文档先占用了名额，取完再删。
- **验证**：读 `search()`，`excluded` 文档的 chunk 仍在 `allowed` 里参与打分，最后才 `hits = [h for h in hits if h.doc_id not in excluded]`。
- **根因**：`starter/kbqa/retriever.py` `search()` 把版本/门店过滤放在取 top-k 之后。
- **修复**：先按 `excluded` 构建 `allowed`（排除这些文档的 chunk），打分与取 top-k 都在 `allowed` 上进行，删掉取完再过滤。commit `8f8054a`。
- **回归测试**：公开 15 道检索题 `results_count=5` 全部满足。

### D7 候选句升序排序，优先选最低分

- **现象**：C01–C08 的 doc 题 0 分，引用到的常常不是真正回答问题的句子。
- **假设**：候选句排序方向反了。
- **验证**：读 `_doc_block()`，`candidates.sort(key=lambda item: (round(item["score"], 2), item["effective_from"]))` 是默认升序，`candidates[0]` 是最低分。
- **根因**：`starter/kbqa/answerer.py::_doc_block` 排序缺 `reverse=True`。
- **修复**：改为按 `(score, effective_from)` 降序（分数高优先，分数接近时生效日期新者优先）。commit `8f8054a`。
- **回归测试**：公开 doc 题 C01–C08 全绿。

### D8 把整篇文档拼进 answer，超长 + 数字轰炸

- **现象**：doc 题 answer 里贴满整篇 OA 公文 / FAQ / 纪要，触发 `answer_length`、`number_flood`。
- **假设**：回答里被塞进了整篇文档正文。
- **验证**：`_answer_doc()` 返回 `self._context(result) + body`，`_context` 把命中文档的所有 chunk 拼起来。
- **根因**：`starter/kbqa/answerer.py::_context` 返回整篇文档。
- **修复**：`_context` 改为返回空串，只保留 `_doc_block` 逐字选取的短引用。commit `8f8054a`。
- **回归测试**：公开 doc 题 answer 均满足长度与数字上限。

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

## 尚未解决 / 已知边界

- 无 LLM Key 的 mock 降级模式已满分；live 模式（配置真实模型后）未在本机验证，`LLM_SETUP.md` 与 `eval/llm_gateway.py preflight` 留待第三关接入时完成。
- 检索为纯 BM25 + 别名扩写，未引入向量检索；跨语言靠别名表的 distinctive token（如 `salmon`→三文鱼poke），覆盖了公开题库，但对知识库之外的近义表述仍依赖词典。
