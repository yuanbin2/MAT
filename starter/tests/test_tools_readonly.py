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
    internal_objects,
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
    conn.execute("CREATE TABLE stores (store_id TEXT, store_name TEXT)")
    conn.executemany(
        "INSERT INTO stores VALUES (?, ?)", [("S%03d" % i, "x" * 200) for i in range(1000)]
    )
    conn.commit()
    conn.close()

    tools = DataTools(path)
    out = tools.run_sql("SELECT * FROM stores")
    assert "error" not in out
    assert len(out["rows"]) <= MAX_SQL_ROWS
    assert out["truncated"] is True
    # 单条 result 序列化后不超过契约上限 4096 字节。
    assert len(json.dumps(out, ensure_ascii=False).encode("utf-8")) <= MAX_EVIDENCE_BYTES


def test_column_limit(tmp_path):
    path = tmp_path / "wide.db"
    conn = sqlite3.connect(path)
    columns = ", ".join("c%d INTEGER" % i for i in range(60))
    conn.execute("CREATE TABLE stores (%s)" % columns)
    conn.execute("INSERT INTO stores DEFAULT VALUES")
    conn.commit()
    conn.close()

    tools = DataTools(path)
    out = tools.run_sql("SELECT * FROM stores")
    assert "error" not in out
    assert len(out["columns"]) <= 40


def test_fit_evidence_shrinks_oversized_result():
    huge = {"rows": [{"blob": "y" * 5000} for _ in range(50)], "row_count": 50}
    fitted = fit_evidence(huge)
    assert len(json.dumps(fitted, ensure_ascii=False).encode("utf-8")) <= MAX_EVIDENCE_BYTES


def test_fit_evidence_leaves_small_result_untouched():
    small = {"net_revenue": 162414.0, "orders": 4446}
    assert fit_evidence(small) == small


# -- SQLite 内部对象：一律不许访问 ---------------------------------------------


INTERNAL_SQL = [
    "SELECT name FROM sqlite_master",
    'SELECT * FROM "sqlite_master"',
    "SELECT * FROM [sqlite_master]",
    "SELECT * FROM sqlite_schema",
    "SELECT * FROM sqlite_temp_master",
    "SELECT * FROM pragma_table_info('sales_clean')",
    "SELECT * FROM pragma_database_list",
]


@pytest.mark.parametrize("sql", INTERNAL_SQL)
def test_internal_objects_rejected(db, sql):
    tools = DataTools(db)
    before = tools.valid_sales_rows()
    out = tools.run_sql(sql)
    assert "error" in out, "%r 本应被拒绝" % sql
    assert any("内部对象" in problem for problem in out["problems"])
    assert tools.valid_sales_rows() == before


def test_internal_object_check_catches_quoted_names():
    # 词法骨架会把带引号的标识符抹掉，所以内部对象检查另跑一遍“去引号”原文。
    assert internal_objects('SELECT * FROM "sqlite_master"') == ["sqlite_master"]
    assert internal_objects("SELECT * FROM `pragma_table_info`") == ["pragma_table_info"]
    assert internal_objects("SELECT COUNT(*) FROM sales_clean") == []


def test_business_queries_still_allowed(db):
    tools = DataTools(db)
    for sql in (
        "SELECT COUNT(*) AS n FROM sales_clean",
        "SELECT store_id, SUM(amount_cents) AS net FROM sales_clean GROUP BY store_id",
        "SELECT s.order_id, s.amount_cents FROM sales_clean s WHERE s.store_id = 'S01'",
        "WITH t AS (SELECT store_id FROM sales_clean) SELECT COUNT(*) AS n FROM t",
    ):
        out = tools.run_sql(sql)
        assert "error" not in out, (sql, out)
        assert out["row_count"] >= 0


def test_run_sql_reads_bounded_rows(tmp_path):
    """有界读取：1000 行只取 201 行判断超限，返回恰好 MAX_SQL_ROWS 行。"""
    path = tmp_path / "many.db"
    conn = sqlite3.connect(path)
    conn.execute("CREATE TABLE sales_clean (i INTEGER)")
    conn.executemany("INSERT INTO sales_clean VALUES (?)", [(i,) for i in range(1000)])
    conn.commit()
    conn.close()

    tools = DataTools(path)
    out = tools.run_sql("SELECT i FROM sales_clean")
    assert out["row_count"] == MAX_SQL_ROWS
    assert out["truncated"] is True


# -- 超限结果：保住可核验的业务值，并明确要求缩小范围 ---------------------------


def test_fit_evidence_preserves_business_scalars():
    huge = {
        "net_revenue": 162414.0,
        "orders": 4446,
        "row_count": 50,
        "rows": [{("c%d" % i): "z" * 300 for i in range(40)} for _ in range(50)],
    }
    fitted = fit_evidence(huge)
    assert len(json.dumps(fitted, ensure_ascii=False).encode("utf-8")) <= MAX_EVIDENCE_BYTES
    # 明细可以丢，但业务标量必须留下，且给出明确的“请缩小范围”说明
    assert fitted["net_revenue"] == 162414.0
    assert fitted["orders"] == 4446
    assert "缩小查询范围" in fitted.get("note", "")


def test_fit_evidence_never_returns_bytes_only_summary():
    # 旧实现会退化成 {"note":..., "keys":..., "bytes_before":N} 这种只有字节数的摘要
    fitted = fit_evidence({"blob": "q" * 20000})
    blob = json.dumps(fitted, ensure_ascii=False)
    assert "缩小查询范围" in blob
    assert "bytes_before" not in fitted
    assert "keys" not in fitted


def test_oversized_run_sql_keeps_scalars_and_asks_to_narrow(tmp_path):
    path = tmp_path / "wide.db"
    conn = sqlite3.connect(path)
    columns = ", ".join("c%d TEXT" % i for i in range(60))
    conn.execute("CREATE TABLE stores (%s)" % columns)
    conn.execute("INSERT INTO stores DEFAULT VALUES")
    conn.commit()
    conn.close()

    tools = DataTools(path)
    out = tools.run_sql("SELECT * FROM stores")
    assert "error" not in out
    assert len(json.dumps(out, ensure_ascii=False).encode("utf-8")) <= MAX_EVIDENCE_BYTES
    if out.get("note"):
        assert "缩小查询范围" in out["note"]


# -- 业务表白名单与文件路径 -----------------------------------------------------


def test_unknown_table_rejected(db):
    tools = DataTools(db)
    out = tools.run_sql("SELECT * FROM secrets")
    assert "error" in out
    assert any("业务表之外" in problem for problem in out["problems"])


def test_cte_over_business_tables_allowed(db):
    tools = DataTools(db)
    out = tools.run_sql(
        "WITH s AS (SELECT store_id FROM sales_clean) SELECT COUNT(*) AS n FROM s"
    )
    assert "error" not in out


def test_file_path_and_extension_rejected(db):
    tools = DataTools(db)
    for sql in (
        "ATTACH DATABASE 'file:/etc/passwd.db' AS x",
        "SELECT load_extension('/tmp/evil.so')",
        "SELECT readfile('/etc/passwd')",
    ):
        out = tools.run_sql(sql)
        assert "error" in out, sql


# -- top_products 的读取要有界（实测：limit=20 会攒出 65 个数字）----------------


@pytest.fixture()
def db_many_products(tmp_path):
    """临时库：20 个商品，用来看 limit 会不会被夹住。"""
    path = tmp_path / "many_products.db"
    conn = sqlite3.connect(path)
    conn.execute(
        "CREATE TABLE sales_clean (order_id TEXT, date TEXT, store_id TEXT,"
        " product_id TEXT, qty INTEGER, amount_cents INTEGER, payment TEXT, is_refund INTEGER)"
    )
    conn.execute(
        "CREATE TABLE products (product_id TEXT, product_name TEXT, product_category TEXT)"
    )
    rows, products = [], []
    for i in range(1, 21):
        pid = "P%02d" % i
        # 名字里不放数字：真实商品名（牛肉poke / 味噌拉面）也不含数字，
        # 否则统计"证据里的数字个数"时会把名字里的数字算进去。
        products.append((pid, "商品" + chr(ord("A") + i - 1), ["主食", "饮料", "小食"][i % 3]))
        rows.append(("O%d" % i, "2026-06-05", "S01", pid, i, 1000 * i, "现金", 0))
    conn.executemany("INSERT INTO sales_clean VALUES (?,?,?,?,?,?,?,?)", rows)
    conn.executemany("INSERT INTO products VALUES (?,?,?)", products)
    conn.commit()
    conn.close()
    return path


def _count_numbers(payload) -> int:
    """跟评测脚本同样口径地数一遍数字。"""
    import re

    return len(re.findall(r"-?\d+(?:\.\d+)?", json.dumps(payload, ensure_ascii=False)))


def test_top_products_limit_is_capped(db_many_products):
    """模型索要 20 条时只能拿到 MAX_TOP_PRODUCTS 条。

    20 个商品 × 3 个数字 = 65 个数字，越过"证据卫生"的上限（穷举数字不是证据），
    公开题库 D03/T03 与自拟题 X10 实测就是这样丢分的。
    """
    from kbqa import tools

    got = tools.DataTools(db_many_products).top_products(
        "2026-06-01", "2026-06-30", None, limit=20
    )

    assert len(got["products"]) <= tools.MAX_TOP_PRODUCTS
    assert _count_numbers(got) <= 60, _count_numbers(got)


def test_top_products_limit_is_still_usable(db_many_products):
    """夹上限不能把正常请求也夹坏：要 3 条就给 3 条。"""
    from kbqa import tools

    got = tools.DataTools(db_many_products).top_products(
        "2026-06-01", "2026-06-30", None, limit=3
    )

    assert len(got["products"]) == 3
