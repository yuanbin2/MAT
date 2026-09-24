"""指标规则的最小样例测试：用自建小型 POS 数据，不依赖原始 data/pos.db。

覆盖：闭区间（末日含）、退款计入净额、订单按 order_id 去重、逐日补齐、
零金额行不计入销量/订单、客单价口径。
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

from kbqa.cleaning import build_clean_db
from kbqa.tools import DataTools


def _build(tmp_path: Path, sales, stores=None, products=None) -> DataTools:
    src = tmp_path / "pos.db"
    conn = sqlite3.connect(src)
    conn.executescript(
        """
        CREATE TABLE stores (store_id TEXT PRIMARY KEY, store_name TEXT, category TEXT, district TEXT);
        CREATE TABLE products (product_id TEXT PRIMARY KEY, product_name TEXT, product_category TEXT, unit_price REAL);
        CREATE TABLE sales (order_id TEXT, date TEXT, store_id TEXT, product_id TEXT, qty TEXT, amount TEXT, payment TEXT);
        """
    )
    conn.executemany("INSERT INTO stores VALUES (?,?,?,?)", stores or [("S01", "店一", "拉面", "徐汇")])
    conn.executemany("INSERT INTO products VALUES (?,?,?,?)", products or [("P01", "牛肉poke", "轻食", 38.0)])
    conn.executemany("INSERT INTO sales VALUES (?,?,?,?,?,?,?)", sales)
    conn.commit()
    conn.close()
    clean = tmp_path / "clean.db"
    build_clean_db(src, clean)
    return DataTools(clean)


def _row(order_id, date, store_id="S01", product_id="P01", qty="1", amount="38.00", payment="微信"):
    return (order_id, date, store_id, product_id, qty, amount, payment)


def test_closed_interval_includes_end_day(tmp_path):
    tools = _build(tmp_path, [_row("O1", "2026-06-01"), _row("O2", "2026-06-30")])
    m = tools.query_metrics("2026-06-01", "2026-06-30")
    assert m["net_revenue"] == 76.0
    assert m["orders"] == 2


def test_refund_subtracts_from_net(tmp_path):
    tools = _build(
        tmp_path,
        [_row("O1", "2026-06-01", amount="100.00"),
         _row("O2", "2026-06-01", amount="-20.00")],
    )
    m = tools.query_metrics("2026-06-01", "2026-06-01")
    assert m["net_revenue"] == 80.0
    assert m["refund_amount"] == 20.0


def test_orders_dedup_by_order_id(tmp_path):
    """一张订单两个商品行，订单数只算 1。"""
    tools = _build(
        tmp_path,
        [_row("O1", "2026-06-01", product_id="P01", amount="38.00"),
         _row("O1", "2026-06-01", product_id="P02", amount="15.00")],
        products=[("P01", "牛肉poke", "轻食", 38.0), ("P02", "三文鱼poke", "轻食", 42.0)],
    )
    m = tools.query_metrics("2026-06-01", "2026-06-01")
    assert m["orders"] == 1
    assert m["net_revenue"] == 53.0


def test_qty_is_sales_minus_refund(tmp_path):
    tools = _build(
        tmp_path,
        [_row("O1", "2026-06-01", qty="3", amount="114.00"),
         _row("O2", "2026-06-01", qty="1", amount="-38.00")],
    )
    m = tools.query_metrics("2026-06-01", "2026-06-01")
    assert m["qty"] == 2  # 3 销售 − 1 退款


def test_zero_amount_row_not_counted_as_qty(tmp_path):
    """零金额行既不是销售也不是退款，不能把它当退款减销量。"""
    tools = _build(
        tmp_path,
        [_row("O1", "2026-06-01", qty="2", amount="76.00"),
         _row("O2", "2026-06-01", qty="5", amount="0.00")],
    )
    m = tools.query_metrics("2026-06-01", "2026-06-01")
    assert m["net_revenue"] == 76.0
    assert m["qty"] == 2
    assert m["orders"] == 1


def test_daily_fills_gaps_with_zero(tmp_path):
    tools = _build(tmp_path, [_row("O1", "2026-06-01"), _row("O2", "2026-06-03")])
    days = tools.daily_metrics("2026-06-01", "2026-06-03")["days"]
    assert [d["date"] for d in days] == ["2026-06-01", "2026-06-02", "2026-06-03"]
    assert days[0]["net_revenue"] == 38.0
    assert days[1]["net_revenue"] == 0.0
    assert days[1]["orders"] == 0
    assert days[1]["aov"] is None
    assert days[2]["net_revenue"] == 38.0


def test_aov_rounds_to_2_decimals(tmp_path):
    tools = _build(
        tmp_path,
        [_row("O1", "2026-06-01", amount="50.00"),
         _row("O2", "2026-06-01", amount="50.00"),
         _row("O3", "2026-06-01", amount="50.00")],
    )
    m = tools.query_metrics("2026-06-01", "2026-06-01")
    assert m["orders"] == 3
    assert m["net_revenue"] == 150.0
    assert m["aov"] == 50.0
