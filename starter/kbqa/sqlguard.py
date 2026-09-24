"""SQL 只读闸门与证据体积控制。

`run_sql` 让模型自己写 SQL 查库，所以必须在执行前挡住一切写入：

- **只放行一条语句**，且必须以 ``SELECT`` 或 ``WITH`` 开头、真的带 ``FROM``
  （``SELECT 1``、``SELECT 0 /* from sales */`` 这类常量语句没有查任何表，
  不能当证据）。
- **拒绝写操作与库级操作**：``INSERT/UPDATE/DELETE/DROP/ALTER/CREATE/ATTACH/
  DETACH/PRAGMA/TRUNCATE/VACUUM/REINDEX`` 等一律拒绝。实测 ``mode=ro`` 的连接
  仍允许 ``ATTACH``，所以这层词法闸门不是冗余——它专门补上连接级只读盖不住的
  库级操作。

判断用词法扫描（先把注释、字符串字面量、带引号的标识符抹成空白再取词元），
所以 ``updated_count`` 不会被误判成 ``update``、``WHERE payment = 'update'``
里的 update 是字符串、``/* FROM sales */`` 里的 FROM 也不算数——与评测脚本
``eval/run_eval.py`` 的 ``sql_problems`` 保持同一套判定口径。

另外提供 ``fit_evidence``：把单条证据的 ``result`` 压到契约规定的 4096 字节内。
"""

from __future__ import annotations

import json
import re
from typing import Any

#: 契约硬上限：单条 ``data_evidence.result`` 序列化后不超过 4096 字节。
MAX_EVIDENCE_BYTES = 4096
#: 一次 run_sql 最多返回多少行 / 多少列（先于字节上限，避免结果集过大）。
MAX_SQL_ROWS = 200
MAX_SQL_COLUMNS = 40
#: 单个字符串字段被截断前的最长长度。
MAX_CELL_CHARS = 300

_QUOTES = {"'": "'", '"': '"', "`": "`", "[": "]"}
_TOKEN_RE = re.compile(r"\b\w+\b")

#: 出现即判定为非只读的词元（词法匹配，不做子串匹配）。
WRITE_WORDS = frozenset(
    {
        "insert",
        "update",
        "delete",
        "drop",
        "alter",
        "create",
        "attach",
        "detach",
        "pragma",
        "truncate",
        "vacuum",
        "reindex",
        "replace",
        "begin",
        "commit",
        "rollback",
        "savepoint",
        "release",
        "analyze",
    }
)

#: SQLite 内部对象：系统表与表值 pragma 函数，一律不许业务查询触碰。
#: 覆盖 ``sqlite_master``/``sqlite_schema``/``sqlite_temp_master`` 及所有 ``sqlite_*``、
#: ``pragma_*``（如 ``pragma_table_info``、``pragma_database_list``）。
_INTERNAL_NAME = re.compile(r"(?<![a-z0-9_])((?:sqlite|pragma)_[a-z0-9_]*)")


def sql_skeleton(sql: str) -> tuple[str, int]:
    """把注释、字符串字面量与带引号的标识符抹成空白，返回（骨架, 语句条数）。

    与评测脚本同构：一次从左到右扫描，``'--'`` 这类藏在字符串里的“注释符”
    不会被当成注释；四种引号（``'…'``、``"…"``、`` `…` ``、``[…]``）都按
    SQLite 的规则处理，成对引号视为转义。
    """
    out: list[str] = []
    statements, has_content = 0, False
    i, n = 0, len(sql or "")
    while i < n:
        ch = sql[i]
        if ch == "-" and sql.startswith("--", i):
            end = sql.find("\n", i)
            i = n if end == -1 else end
            out.append(" ")
            continue
        if ch == "/" and sql.startswith("/*", i):
            end = sql.find("*/", i + 2)
            i = n if end == -1 else end + 2
            out.append(" ")
            continue
        if ch in _QUOTES:
            close = _QUOTES[ch]
            j = i + 1
            while j < n:
                if sql[j] == close:
                    if close != "]" and j + 1 < n and sql[j + 1] == close:
                        j += 2
                        continue
                    break
                j += 1
            i = j + 1
            out.append(" ")
            has_content = True
            continue
        if ch == ";":
            if has_content:
                statements += 1
            has_content = False
            out.append(" ")
            i += 1
            continue
        if not ch.isspace():
            has_content = True
        out.append(ch)
        i += 1
    if has_content:
        statements += 1
    return "".join(out), statements


def internal_objects(sql: Any) -> list[str]:
    """找出被引用的 SQLite 内部对象名（含被引号包起来、绕过词元扫描的写法）。

    词法骨架会把带引号的标识符抹成空白，``FROM "sqlite_master"`` 因此躲得过词元检查，
    所以这里在“去掉引号字符”的原文上再扫一遍。
    """
    relaxed = re.sub(r"[\"'`\[\]]", "", (sql or "").lower())
    return sorted({match.group(1) for match in _INTERNAL_NAME.finditer(relaxed)})


def check_readonly_sql(sql: Any) -> list[str]:
    """返回问题列表；空列表代表这条 SQL 是安全、只读、且真的查了表。"""
    if not isinstance(sql, str) or not sql.strip():
        return ["不是非空字符串"]
    skeleton, statements = sql_skeleton(sql)
    tokens = _TOKEN_RE.findall(skeleton.lower())
    problems: list[str] = []
    if statements > 1:
        problems.append("包含多条语句（只允许一条 SELECT）")
    if not tokens or tokens[0] not in ("select", "with"):
        problems.append("不是以 SELECT（或 WITH … SELECT）开头")
    if "from" not in tokens:
        problems.append("没有 FROM，没有真的查过任何表")
    writes = sorted(set(tokens) & WRITE_WORDS)
    if any(a == "replace" and b == "into" for a, b in zip(tokens, tokens[1:])):
        writes.append("replace into")
    if writes:
        problems.append("出现了写操作关键字：%s" % "、".join(writes))
    internal = internal_objects(sql)
    if internal:
        problems.append("访问了 SQLite 内部对象：%s（只允许业务表）" % "、".join(internal))
    return problems


def _dump(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, default=str)


def _size(value: Any) -> int:
    return len(_dump(value).encode("utf-8"))


def _trim_cells(rows: list[dict]) -> list[dict]:
    trimmed = []
    for row in rows:
        trimmed.append(
            {
                key: (value[:MAX_CELL_CHARS] if isinstance(value, str) else value)
                for key, value in row.items()
            }
        )
    return trimmed


#: 证据里属于“元信息”而非业务数据的键：SQL 原文、字段名、截断说明与字节数。
#: 压体积时不当业务值保留；取证据数字时也不从这里取（统一由本常量约束）。
EVIDENCE_META_KEYS = frozenset({"sql", "columns", "keys", "note", "bytes_before", "truncated"})

#: 明细被省略时给出的说明：明确要求缩小范围，而不是只回一个字节数。
NARROW_NOTE = (
    "结果超过证据体积上限 4096 字节，明细已省略；"
    "请缩小查询范围（收窄日期区间、门店/商品或减少返回字段）后重新查询"
)


def fit_evidence(result: Any, limit: int = MAX_EVIDENCE_BYTES) -> Any:
    """把 ``result`` 压到 ``limit`` 字节以内（保持 JSON 可序列化）。

    逐级降级，越靠后的手段越有损，但**始终保住可核验的业务值**：

    1. 已经够小就原样返回；
    2. 若形如 ``{"rows": [...]}``，逐步截断 ``rows``；
    3. 过长的字符串字段截断到 ``MAX_CELL_CHARS``；
    4. 仍超限就丢明细、**保留标量业务值**（``net_revenue``/``orders``/``row_count`` …），
       并附上明确的“请缩小查询范围”提示——不返回只有字节数的无语义摘要；
    5. 最坏情况只保留数值型标量 + 提示（仍不出现“只剩字节数”的摘要）。
    """
    if _size(result) <= limit:
        return result

    if isinstance(result, dict) and isinstance(result.get("rows"), list):
        rows = result["rows"]
        # 逐行裁到 1 行为止；单行仍超限就交给后面截字段/丢明细。
        while len(rows) > 1 and _size(dict(result, rows=rows)) > limit:
            rows = rows[: max(1, int(len(rows) * 0.8))]
        candidate = dict(result, rows=rows, truncated=True)
        if _size(candidate) <= limit:
            return candidate
        result = candidate
        result = dict(result, rows=_trim_cells(result["rows"]))
        if _size(result) <= limit:
            return result

    # 4) 丢明细、保标量业务值
    if isinstance(result, dict):
        scalars = {
            key: value
            for key, value in result.items()
            if not isinstance(value, (dict, list, tuple)) and str(key) != "sql"
        }
        slim = dict(scalars, truncated=True, note=NARROW_NOTE)
        if "rows" in result:
            slim["rows"] = []
        if _size(slim) <= limit:
            return slim
        result = slim

    # 5) 兜底：只留数值型标量 + 提示，绝不返回“只有字节数”的摘要
    numeric: dict = {}
    if isinstance(result, dict):
        numeric = {
            key: value
            for key, value in result.items()
            if isinstance(value, (int, float)) and not isinstance(value, bool)
        }
    fallback = dict(numeric, note=NARROW_NOTE, truncated=True)
    if _size(fallback) <= limit:
        return fallback
    return {"note": NARROW_NOTE, "truncated": True}
