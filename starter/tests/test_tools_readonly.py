"""DataTools 只读闸门的回归测试。

覆盖两条独立防线，任何一条被绕过都必须有测试为红：

1. 连接层：`open_readonly` 用 URI `mode=ro` + `query_only`，写入在 SQLite 层就被拒；
2. 语法层：`run_sql` 只放行单条、以 SELECT/WITH 开头、真的带 FROM 的查询，
   写入与库级操作（尤其 `ATTACH`——`mode=ro` 照样放行）在执行前即被拒绝。

所有测试都在**临时数据库副本**上跑，断言操作前后行数不变。
"""

from __future__ import annotations

import json
import sqlite3

import pytest

from kbqa.sqlguard import (
    MAX_EVIDENCE_BYTES,
    MAX_SQL_ROWS,
    check_readonly_sql,
    fit_evidence,
)
from kbqa.tools import DataTools


@pytest.fixture()
def db(tmp_path):
    """一个临时数据库副本，结构与 clean.db 的关键列一致。"""
    path = tmp_path / "clean_copy.db"
    conn = sqlite3.connect(path)
    conn.execute(
        "CREATE TABLE sales_clean (order_id TEXT, date TEXT, store_id TEXT,"
        " product_id TEXT, qty INTEGER, amount_cents INTEGER, payment TEXT, is_refund INTEGER)"
    )
    conn.executemany(
        "INSERT INTO sales_clean VALUES (?,?,?,?,?,?,?,?)",
        [
            ("O1", "2026-07-01", "S01", "P01", 2, 2000, "现金", 0),
            ("O2", "2026-07-02", "S02", "P02", 1, 500, "微信", 0),
            ("O3", "2026-07-02", "S01", "P01", -1, -2000, "现金", 1),
        ],
    )
    conn.commit()
    conn.close()
    return path


# -- 正常只读查询仍可用 ---------------------------------------------------------


def test_select_still_works(db):
    tools = DataTools(db)
    assert tools.valid_sales_rows() == 3
    out = tools.run_sql(
        "SELECT store_id, SUM(amount_cents) AS net FROM sales_clean GROUP BY store_id ORDER BY store_id"
    )
    assert "error" not in out
    assert out["row_count"] == 2
    assert [row["store_id"] for row in out["rows"]] == ["S01", "S02"]
    assert out["columns"] == ["store_id", "net"]


def test_cte_select_works(db):
    tools = DataTools(db)
    out = tools.run_sql(
        "WITH s AS (SELECT store_id FROM sales_clean) SELECT COUNT(*) AS n FROM s"
    )
    assert "error" not in out
    assert out["rows"][0]["n"] == 3


# -- 写入与库级操作：拒绝且行数不变 ---------------------------------------------


WRITE_SQL = [
    "DELETE FROM sales_clean",
    "UPDATE sales_clean SET qty = 0",
    "DROP TABLE sales_clean",
    "INSERT INTO sales_clean (order_id) VALUES ('X')",
    "CREATE TABLE evil (a int)",
    "ALTER TABLE sales_clean ADD COLUMN extra int",
    "PRAGMA writable_schema = 1",
    "ATTACH DATABASE 'evil.db' AS evil",  # mode=ro 也放行 ATTACH，必须靠这层挡住
    "DETACH DATABASE evil",
    "VACUUM",
]


@pytest.mark.parametrize("sql", WRITE_SQL)
def test_write_and_library_ops_rejected_rows_unchanged(db, sql):
    tools = DataTools(db)
    before = tools.valid_sales_rows()
    out = tools.run_sql(sql)
    assert "error" in out, "%r 本应被拒绝" % sql
    assert out["problems"], "%r 被拒绝时应说明原因" % sql
    # 关键：换了临时副本，操作后行数必须一模一样。
    assert tools.valid_sales_rows() == before


def test_multiple_statements_rejected(db):
    tools = DataTools(db)
    before = tools.valid_sales_rows()
    out = tools.run_sql("SELECT 1 FROM sales_clean; DROP TABLE sales_clean")
    assert "error" in out
    assert tools.valid_sales_rows() == before


def test_constant_select_without_from_rejected(db):
    tools = DataTools(db)
    # 常量语句没有查任何表，不能当证据；“注释里藏 FROM”同样不认。
    assert "error" in tools.run_sql("SELECT 1")
    assert "error" in tools.run_sql("SELECT 0 /* from sales_clean */")
    assert "error" in tools.run_sql("SELECT 0 -- from sales_clean")


def test_connection_is_readonly_even_if_guard_bypassed(db):
    """即便语法闸门被绕过，连接层的 mode=ro 也必须兜住。"""
    tools = DataTools(db)
    with pytest.raises(sqlite3.OperationalError):
        tools.conn.execute("DELETE FROM sales_clean")
    with pytest.raises(sqlite3.OperationalError):
        tools.conn.execute("DROP TABLE sales_clean")


# -- 词法判断：不误伤合法的只读查询 ---------------------------------------------


def test_lexical_false_positives_are_allowed():
    assert check_readonly_sql("SELECT updated_count FROM sales_clean") == []
    assert check_readonly_sql("SELECT * FROM sales_clean WHERE payment = 'update'") == []
    assert check_readonly_sql(
        "WITH t AS (SELECT order_id FROM sales_clean) SELECT * FROM t"
    ) == []


def test_guard_reports_specific_problems():
    assert any("多条语句" in problem for problem in check_readonly_sql("SELECT 1 FROM a; SELECT 2 FROM b"))
    assert any("SELECT" in problem for problem in check_readonly_sql("DELETE FROM a"))
    assert any("FROM" in problem for problem in check_readonly_sql("SELECT 1"))


# -- 结果体积上限 ---------------------------------------------------------------


def test_row_limit_and_byte_limit(tmp_path):
    path = tmp_path / "big.db"
    conn = sqlite3.connect(path)
    conn.execute("CREATE TABLE big (i INTEGER, s TEXT)")
    conn.executemany("INSERT INTO big VALUES (?, ?)", [(i, "x" * 200) for i in range(1000)])
    conn.commit()
    conn.close()

    tools = DataTools(path)
    out = tools.run_sql("SELECT * FROM big")
    assert "error" not in out
    assert len(out["rows"]) <= MAX_SQL_ROWS
    assert out["truncated"] is True
    # 单条 result 序列化后不超过契约上限 4096 字节。
    assert len(json.dumps(out, ensure_ascii=False).encode("utf-8")) <= MAX_EVIDENCE_BYTES


def test_column_limit(tmp_path):
    path = tmp_path / "wide.db"
    conn = sqlite3.connect(path)
    columns = ", ".join("c%d INTEGER" % i for i in range(60))
    conn.execute("CREATE TABLE wide (%s)" % columns)
    conn.execute("INSERT INTO wide DEFAULT VALUES")
    conn.commit()
    conn.close()

    tools = DataTools(path)
    out = tools.run_sql("SELECT * FROM wide")
    assert "error" not in out
    assert len(out["columns"]) <= 40


def test_fit_evidence_shrinks_oversized_result():
    huge = {"rows": [{"blob": "y" * 5000} for _ in range(50)], "row_count": 50}
    fitted = fit_evidence(huge)
    assert len(json.dumps(fitted, ensure_ascii=False).encode("utf-8")) <= MAX_EVIDENCE_BYTES


def test_fit_evidence_leaves_small_result_untouched():
    small = {"net_revenue": 162414.0, "orders": 4446}
    assert fit_evidence(small) == small
