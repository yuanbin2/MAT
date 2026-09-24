"""第一关：清洗与指标口径的回归测试。

口径依据 KB-001（指标口径手册 v3）。黄金值来自随作业包一起提供的
``data/pos.db``，用于防止清洗或指标算法回归；换数据重建后这些“绝对值”断言
会相应变化，但“不变式”断言（原始−保留=剔除、保留=销售+退款、逐日补齐、
闭区间）会继续成立。
"""

from __future__ import annotations


def test_metrics_summary_june_matches_kb001(client):
    """KB-001 v3 的完整指标口径：退款计入净营业额、客单价除以有效订单数。"""
    r = client.get(
        "/api/metrics/summary",
        params={"start": "2026-06-01", "end": "2026-06-30"},
    )
    assert r.status_code == 200
    b = r.json()
    assert b["net_revenue"] == 156757.0
    assert b["refund_amount"] == 953.0
    assert b["orders"] == 4311
    assert b["aov"] == 36.36
    assert b["qty"] == 6496


def test_metrics_summary_single_day_closed_interval(client):
    """末日也是闭区间：单日查询要能取到当天的数。"""
    r = client.get(
        "/api/metrics/summary",
        params={"start": "2026-06-18", "end": "2026-06-18",
                "store_id": "S02", "product_id": "P06"},
    )
    assert r.status_code == 200
    b = r.json()
    assert b["net_revenue"] == 3625.0
    assert b["refund_amount"] == 0.0
    assert b["orders"] == 53
    assert b["aov"] == 68.4
    assert b["qty"] == 125


def test_metrics_summary_empty_range_zero_and_null_aov(client):
    """区间没有数据时数值为 0、aov 为 null，不报错（契约 §2）。"""
    r = client.get(
        "/api/metrics/summary",
        params={"start": "2026-09-01", "end": "2026-09-30"},
    )
    assert r.status_code == 200
    b = r.json()
    assert b["net_revenue"] == 0.0
    assert b["refund_amount"] == 0.0
    assert b["orders"] == 0
    assert b["aov"] is None
    assert b["qty"] == 0


def test_metrics_daily_fills_every_day_and_closed_interval(client):
    """逐日接口：区间内每一天都有一条，末日包含，无销售的日期补 0。"""
    r = client.get(
        "/api/metrics/daily",
        params={"start": "2026-06-08", "end": "2026-06-12", "store_id": "S03"},
    )
    assert r.status_code == 200
    days = r.json()["days"]
    assert [d["date"] for d in days] == [
        "2026-06-08", "2026-06-09", "2026-06-10", "2026-06-11", "2026-06-12",
    ]
    for d in days[:4]:
        assert d["net_revenue"] == 0.0
        assert d["orders"] == 0
        assert d["aov"] is None
    last = days[-1]
    assert last["net_revenue"] == 998.0
    assert last["orders"] == 27
    assert last["aov"] == 36.96


def test_metrics_store_and_product_filter(client):
    """门店与商品筛选同时生效。"""
    r = client.get(
        "/api/metrics/summary",
        params={"start": "2026-08-01", "end": "2026-08-31", "product_id": "P21"},
    )
    b = r.json()
    assert b["net_revenue"] == 11024.0
    assert b["refund_amount"] == 16.0
    assert b["orders"] == 461
    assert b["qty"] == 689


def test_cleaning_report_consistency(client):
    """数据质量面板的账要对得上：原始−保留=剔除，保留=销售+退款。"""
    rep = client.get("/api/data_quality").json()["cleaning_report"]
    assert rep["raw_rows"] == 18628
    assert rep["kept_rows"] == 18290
    assert rep["kept_sales_rows"] + rep["kept_refund_rows"] == rep["kept_rows"]
    removed = rep["removed"]
    assert rep["raw_rows"] - rep["kept_rows"] == (
        removed["1_unparseable_date"] + removed["2_empty_amount"]
        + removed["3_qty_le_zero"] + removed["4_store_not_in_stores"]
        + removed["5_product_not_in_products"] + removed["6_duplicate_row"]
        + removed["note_unparseable_amount"]
    )
    # 六类剔除原因都有实际命中（这 6 类在本数据集里都存在脏数据）。
    for key in ("1_unparseable_date", "2_empty_amount", "3_qty_le_zero",
                "4_store_not_in_stores", "5_product_not_in_products",
                "6_duplicate_row"):
        assert removed[key] > 0, "剔除原因 %s 应命中" % key


def test_health_valid_sales_rows_and_kb_docs(client):
    """健康检查：清洗后行数与进入索引的文档数。"""
    b = client.get("/api/health").json()
    assert b["valid_sales_rows"] == 18290
    assert b["kb_docs"] == 35
    assert b["status"] == "ok"


def test_metrics_rejects_bad_date(client):
    """非法日期格式返回 400（契约只接受 YYYY-MM-DD）。"""
    r = client.get(
        "/api/metrics/summary",
        params={"start": "2026/06/01", "end": "2026-06-30"},
    )
    assert r.status_code == 400
