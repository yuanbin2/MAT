"""黄金值回归测试：仅针对随作业包提供的原始 ``data/pos.db`` 运行。

这些断言写死了原始数据的数值，用于防止清洗/指标算法在原始数据上回归。
评审换数据重建时（``data/`` 被替换），本文件的所有用例会自动 skip，
不会因为数值对不上而误报失败。换数据后的规则正确性由
``test_cleaning_rules.py`` / ``test_metrics_rules.py`` 用自建小数据覆盖。
"""

from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

# 原始 data/pos.db 的 SHA-256 指纹。
_ORIGINAL_DB_SHA256 = "b92ece8f017a7313af8b90f3b31c4a49acca010ca154fa8e9c525a2f053e20e1"


def _data_is_original() -> bool:
    db = Path(__file__).resolve().parents[2] / "data" / "pos.db"
    if not db.exists():
        return False
    return hashlib.sha256(db.read_bytes()).hexdigest() == _ORIGINAL_DB_SHA256


@pytest.fixture(autouse=True)
def _require_original_data():
    if not _data_is_original():
        pytest.skip("黄金值测试仅针对原始 data/pos.db，当前数据已被替换")


def test_metrics_summary_june_matches_kb001(client):
    r = client.get("/api/metrics/summary", params={"start": "2026-06-01", "end": "2026-06-30"})
    assert r.status_code == 200
    b = r.json()
    assert b["net_revenue"] == 156757.0
    assert b["refund_amount"] == 953.0
    assert b["orders"] == 4311
    assert b["aov"] == 36.36
    assert b["qty"] == 6496


def test_metrics_summary_single_day_closed_interval(client):
    r = client.get(
        "/api/metrics/summary",
        params={"start": "2026-06-18", "end": "2026-06-18", "store_id": "S02", "product_id": "P06"},
    )
    b = r.json()
    assert b["net_revenue"] == 3625.0
    assert b["refund_amount"] == 0.0
    assert b["orders"] == 53
    assert b["aov"] == 68.4
    assert b["qty"] == 125


def test_metrics_summary_empty_range(client):
    r = client.get("/api/metrics/summary", params={"start": "2026-09-01", "end": "2026-09-30"})
    b = r.json()
    assert b["net_revenue"] == 0.0
    assert b["orders"] == 0
    assert b["aov"] is None
    assert b["qty"] == 0


def test_metrics_daily_fills_every_day(client):
    r = client.get(
        "/api/metrics/daily",
        params={"start": "2026-06-08", "end": "2026-06-12", "store_id": "S03"},
    )
    days = r.json()["days"]
    assert [d["date"] for d in days] == [
        "2026-06-08", "2026-06-09", "2026-06-10", "2026-06-11", "2026-06-12",
    ]
    for d in days[:4]:
        assert d["net_revenue"] == 0.0 and d["orders"] == 0 and d["aov"] is None
    assert days[-1]["net_revenue"] == 998.0
    assert days[-1]["orders"] == 27
    assert days[-1]["aov"] == 36.96


def test_metrics_store_and_product_filter(client):
    r = client.get(
        "/api/metrics/summary",
        params={"start": "2026-08-01", "end": "2026-08-31", "product_id": "P21"},
    )
    b = r.json()
    assert b["net_revenue"] == 11024.0
    assert b["refund_amount"] == 16.0
    assert b["orders"] == 461
    assert b["qty"] == 689


def test_cleaning_report_golden_values(client):
    rep = client.get("/api/data_quality").json()["cleaning_report"]
    assert rep["raw_rows"] == 18628
    assert rep["kept_rows"] == 18290
    assert rep["kept_sales_rows"] + rep["kept_refund_rows"] == rep["kept_rows"]
    removed = rep["removed"]
    assert removed["1_unparseable_date"] == 8
    assert removed["2_empty_amount"] == 150
    assert removed["3_qty_le_zero"] == 30
    assert removed["4_store_not_in_stores"] == 10
    assert removed["5_product_not_in_products"] == 40
    assert removed["6_duplicate_row"] == 100
    # 原始数据里没有“金额/数量无法解析”两类异常。
    assert removed["7_unparseable_amount"] == 0
    assert removed["8_qty_unparseable"] == 0
    assert rep["raw_rows"] - rep["kept_rows"] == sum(removed.values())


def test_health_golden_values(client):
    b = client.get("/api/health").json()
    assert b["valid_sales_rows"] == 18290
    assert b["kb_docs"] == 35
    assert b["status"] == "ok"
