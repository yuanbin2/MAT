"""清洗规则的最小样例测试：不依赖原始 ``data/pos.db``。

直接驱动 ``kbqa.cleaning`` 的解析函数与 ``clean_rows``，用自建的小型行集合
验证 KB-001 v3 的规范化与逐类剔除顺序、去重、退款识别与台账对账。
"""

from __future__ import annotations

from kbqa.cleaning import (
    clean_rows,
    normalize_code,
    parse_amount,
    parse_date,
    parse_qty,
)

# 销售行 dict 字段与 clean_rows 读取的键一一对应。
def sale(
    order_id="O1", date="2026-06-01", store_id="S01", product_id="P01",
    qty="1", amount="38.00", payment="微信",
):
    return {
        "order_id": order_id, "date": date, "store_id": store_id,
        "product_id": product_id, "qty": qty, "amount": amount, "payment": payment,
    }


def run(sales, store_ids=("S01",), product_ids=("P01",)):
    rows, report = clean_rows(sales, set(store_ids), set(product_ids))
    return rows, report


# -- 解析函数 ---------------------------------------------------------------


def test_parse_qty_integer():
    assert parse_qty("3") == 3
    assert parse_qty("-2") == -2


def test_parse_qty_non_integer_not_truncated():
    """KB-001 §2.4“按整数解析”：1.5 不能被静默截断成 1。"""
    assert parse_qty("1.5") is None


def test_parse_qty_lossless_decimal_ok():
    # 值无损地等于整数，接受。
    assert parse_qty("1.0") == 1


def test_parse_qty_unparseable():
    assert parse_qty("") is None
    assert parse_qty("abc") is None


def test_parse_amount_currency_and_plain():
    assert parse_amount("¥38.00") == (3800, "ok")
    assert parse_amount("38.00") == (3800, "ok")
    assert parse_amount("-25.00") == (-2500, "ok")


def test_parse_amount_empty_and_bad():
    assert parse_amount("") == (None, "empty")
    assert parse_amount("abc") == (None, "bad")


def test_parse_date_formats():
    assert parse_date("2026-06-01") == "2026-06-01"
    assert parse_date("2026/6/1") == "2026-06-01"
    # DD-MM-YYYY：日在前、月在后。
    assert parse_date("25-07-2026") == "2026-07-25"


def test_parse_date_invalid():
    assert parse_date("2026-13-45") is None  # 格式对但日历不存在
    assert parse_date("N/A") is None
    assert parse_date("") is None


def test_normalize_code():
    assert normalize_code(" s01") == "S01"
    assert normalize_code("S02 ") == "S02"


# -- 剔除顺序与归类 ---------------------------------------------------------


def test_removal_reasons_are_disjoint_and_ordered():
    """每个问题行只归入最先命中的那一类，六类 + 两类无法解析都覆盖到。"""
    sales = [
        sale(date="N/A"),                       # 1 日期无法解析
        sale(amount=""),                        # 2 金额为空
        sale(qty="0"),                          # 3 数量 ≤ 0
        sale(store_id="S99"),                   # 4 门店外键无效
        sale(product_id="P99"),                 # 5 商品外键无效
        sale(amount="oops"),                    # 7 金额无法解析（非空）
        sale(qty="1.5"),                        # 8 数量无法解析（非整数）
    ]
    _, report = run(sales)
    assert report.removed["1_unparseable_date"] == 1
    assert report.removed["2_empty_amount"] == 1
    assert report.removed["3_qty_le_zero"] == 1
    assert report.removed["4_store_not_in_stores"] == 1
    assert report.removed["5_product_not_in_products"] == 1
    assert report.removed["7_unparseable_amount"] == 1
    assert report.removed["8_qty_unparseable"] == 1
    assert report.removed["6_duplicate_row"] == 0
    assert report.kept_rows == 0


def test_duplicate_vs_multi_product_order():
    """完全重复只留一条；共用订单号的不同商品行全部保留。"""
    dup = sale(order_id="O1", product_id="P01", amount="20.00")
    same_order_diff_product = sale(order_id="O1", product_id="P02", amount="15.00")
    rows, report = run(
        [dup, dup, same_order_diff_product],
        store_ids=("S01",), product_ids=("P01", "P02"),
    )
    assert report.removed["6_duplicate_row"] == 1
    assert report.kept_rows == 2
    # 两条不同商品行都保留，且同属一个订单。
    assert sorted(r[3] for r in rows) == ["P01", "P02"]


def test_refund_detected_by_negative_amount():
    rows, report = run(
        [sale(amount="20.00"), sale(amount="-5.00", order_id="O2")],
        store_ids=("S01",), product_ids=("P01",),
    )
    assert report.kept_sales_rows == 1
    assert report.kept_refund_rows == 1
    assert rows[1][-1] == 1  # is_refund


def test_zero_amount_row_is_neither_sales_nor_refund():
    """零金额行保留（不算销售也不算退款），台账里 sales/refund 计数不含它。"""
    _, report = run(
        [sale(amount="20.00"), sale(amount="0.00", order_id="O2")],
        store_ids=("S01",), product_ids=("P01",),
    )
    assert report.kept_rows == 2
    assert report.kept_sales_rows == 1
    assert report.kept_refund_rows == 0


def test_ledger_adds_up():
    """原始 − 保留 = 全部剔除原因之和。"""
    sales = [
        sale(date="N/A"),
        sale(amount=""),
        sale(qty="1.5"),
        sale(product_id="P99"),
        sale(amount="38.00"),
    ]
    _, report = run(sales)
    assert report.raw_rows == 5
    assert report.raw_rows - report.kept_rows == sum(report.removed.values())
    assert report.kept_rows == report.kept_sales_rows + report.kept_refund_rows
