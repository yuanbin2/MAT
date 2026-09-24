"""把原始 sales 清洗进 var/clean.db，指标都查这张表。

清洗口径以 KB-001（指标口径手册 v3）为准：

1. 先规范化（§2）：门店/商品编号去首尾空白并转大写；日期接受三种格式
   （YYYY-MM-DD / YYYY/M/D / DD-MM-YYYY，第三种日在前月在后）；
   金额去掉 ``¥`` 前缀与空白后按数字解析；数量按整数解析。
2. 再按顺序剔除（§3）：
   日期无法解析 → 金额为空 → 数量 ≤ 0 → 门店外键无效 → 商品外键无效 →
   完全重复（七个字段规范化后完全一致只保留一条）；
   另把“金额无法解析”“数量无法按整数解析”两类数据异常单独归类剔除。
"""

from __future__ import annotations

import json
import re
import sqlite3
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Iterable, Optional

#: 金额里的 `¥` / `￥` 去掉再按数字解析（KB-001 §2.3）。
_CURRENCY = str.maketrans("", "", "¥￥ \t　")

#: 剔除原因，顺序固定，供数据质量面板与评测展示。
#: 前六类是 KB-001 §3 明文规定的；后两类是手册未单列、但现实中存在的
#: “无法解析”情形，单独归类保证“原始 − 保留 = 各类剔除之和”在任何数据下都成立。
REMOVAL_REASONS = (
    "1_unparseable_date",
    "2_empty_amount",
    "3_qty_le_zero",
    "4_store_not_in_stores",
    "5_product_not_in_products",
    "6_duplicate_row",
    "7_unparseable_amount",
    "8_qty_unparseable",
)

#: 可恢复的格式问题（规范化后保留，不算剔除），单独统计以便面板区分。
NORMALIZED_FIELDS = ("currency_amount", "store_code", "product_code", "date_format")

_ISO_ONLY = re.compile(r"\d{4}-\d{2}-\d{2}")


def parse_amount(value: Optional[str]) -> tuple[Optional[int], str]:
    """返回 (分, 状态)。状态取值：`ok`、`empty`、`bad`。

    KB-001 §2.3 与 §3.2：`¥38.00` 与 `38.00` 是同一个金额；空金额直接剔除，**不回填**。
    """
    text = (value or "").translate(_CURRENCY)
    if not text:
        return None, "empty"
    try:
        cents = int((Decimal(text) * 100).to_integral_value())
    except (InvalidOperation, ValueError):
        return None, "bad"
    return cents, "ok"


def parse_qty(value: Optional[str]) -> Optional[int]:
    """KB-001 §2.4：按整数解析。

    解析失败或**非整数**（如 ``1.5``）都返回 None——不静默截断，
    由调用方归入“数量无法解析”剔除。
    """
    text = (value or "").strip()
    if not text:
        return None
    try:
        number = Decimal(text)
    except (InvalidOperation, ValueError):
        return None
    if number != number.to_integral_value():
        # 有小数部分，不是整数，不能悄悄取整。
        return None
    return int(number)


def normalize_code(value: Optional[str]) -> str:
    """KB-001 §2.1：门店/商品编号去掉首尾空白并转大写。"""
    return (value or "").strip().upper()


def parse_date(value: Optional[str]) -> Optional[str]:
    """KB-001 §2.2：三种日期格式归一为 ``YYYY-MM-DD``，无法解析返回 None。

    - ``YYYY-MM-DD``（含 ``YYYY-M-D`` 这种缺前导零的写法）
    - ``YYYY/M/D``
    - ``DD-MM-YYYY``：旧 POS 格式，**日在前、月在后**。

    即便字符串匹配了格式，只要不是真实存在的日历日期（如 ``2026-13-45``），
    也视为无法解析。
    """
    text = (value or "").strip()
    if not text:
        return None

    year_first = re.fullmatch(r"(\d{4})-(\d{1,2})-(\d{1,2})", text)
    if year_first:
        iso = "%04d-%02d-%02d" % (
            int(year_first.group(1)), int(year_first.group(2)), int(year_first.group(3)))
    else:
        slash = re.fullmatch(r"(\d{4})/(\d{1,2})/(\d{1,2})", text)
        if slash:
            iso = "%04d-%02d-%02d" % (
                int(slash.group(1)), int(slash.group(2)), int(slash.group(3)))
        else:
            day_first = re.fullmatch(r"(\d{1,2})-(\d{1,2})-(\d{4})", text)
            if not day_first:
                return None
            # 日在第一个数字、月在第二个（KB-001 §2.2）。
            iso = "%04d-%02d-%02d" % (
                int(day_first.group(3)), int(day_first.group(2)), int(day_first.group(1)))

    try:
        date.fromisoformat(iso)
    except ValueError:
        return None
    return iso


@dataclass
class CleaningReport:
    raw_rows: int = 0
    kept_rows: int = 0
    kept_sales_rows: int = 0
    kept_refund_rows: int = 0
    removed: dict[str, int] = field(default_factory=lambda: {k: 0 for k in REMOVAL_REASONS})
    normalized: dict[str, int] = field(
        default_factory=lambda: {k: 0 for k in NORMALIZED_FIELDS})

    @property
    def removed_total(self) -> int:
        return sum(self.removed.values())

    def as_dict(self) -> dict:
        return {
            "raw_rows": self.raw_rows,
            "removed": dict(self.removed),
            "kept_rows": self.kept_rows,
            "kept_sales_rows": self.kept_sales_rows,
            "kept_refund_rows": self.kept_refund_rows,
            "normalized": dict(self.normalized),
        }


def open_readonly(path: Path) -> sqlite3.Connection:
    """打开数据库。"""
    conn = sqlite3.connect(path.as_posix(), check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn


def clean_rows(
    rows: Iterable[sqlite3.Row],
    store_ids: set[str],
    product_ids: set[str],
) -> tuple[list[tuple], CleaningReport]:
    """按 KB-001 v3 规范化并逐类剔除，返回（清洗后的行，清洗台账）。

    返回的每一行是 ``(order_id, date_iso, store_id, product_id, qty, amount_cents,
    payment, is_refund)``，其中 ``date_iso`` 已统一为 ``YYYY-MM-DD``。
    """
    report = CleaningReport()
    kept: list[tuple] = []
    seen: set[tuple] = set()

    for row in rows:
        report.raw_rows += 1

        raw_store = row["store_id"]
        raw_product = row["product_id"]
        raw_date = row["date"]
        raw_amount = row["amount"]
        raw_qty = row["qty"]
        raw_payment = row["payment"]

        store = normalize_code(raw_store)
        product = normalize_code(raw_product)

        # §3.1 日期无法解析
        date_iso = parse_date(raw_date)
        if date_iso is None:
            report.removed["1_unparseable_date"] += 1
            continue

        # §3.2 金额为空（不回填）；非空但无法解析的金额单独归类剔除
        cents, status = parse_amount(raw_amount)
        if status == "empty":
            report.removed["2_empty_amount"] += 1
            continue
        if status == "bad":
            report.removed["7_unparseable_amount"] += 1
            continue

        # §3.3 数量 ≤ 0；无法按整数解析（非整数/非数字）单独归类
        qty = parse_qty(raw_qty)
        if qty is None:
            report.removed["8_qty_unparseable"] += 1
            continue
        if qty <= 0:
            report.removed["3_qty_le_zero"] += 1
            continue

        # §3.4 / §3.5 外键无效（规范化后判断）
        if store not in store_ids:
            report.removed["4_store_not_in_stores"] += 1
            continue
        if product not in product_ids:
            report.removed["5_product_not_in_products"] += 1
            continue

        # §3.6 完全重复：七个字段规范化后完全一致，只保留一条
        order_id = (row["order_id"] or "").strip()
        payment = (raw_payment or "").strip()
        key = (order_id, date_iso, store, product, qty, cents, payment)
        if key in seen:
            report.removed["6_duplicate_row"] += 1
            continue
        seen.add(key)

        is_refund = 1 if cents < 0 else 0
        kept.append((order_id, date_iso, store, product, qty, cents, payment, is_refund))

        # 记录可恢复的格式问题（已规范化保留，未剔除）
        if raw_amount and ("¥" in raw_amount or "￥" in raw_amount):
            report.normalized["currency_amount"] += 1
        if raw_store and raw_store != store:
            report.normalized["store_code"] += 1
        if raw_product and raw_product != product:
            report.normalized["product_code"] += 1
        if raw_date and not _ISO_ONLY.fullmatch((raw_date or "").strip()):
            report.normalized["date_format"] += 1

    report.kept_rows = len(kept)
    # 销售行 / 退款行按金额符号区分（KB-001 §4）：零金额行两者都不是，
    # 不计入销售也不计入退款，所以不能用 `is_refund`（它把零金额当“非退款”）。
    report.kept_sales_rows = sum(1 for row in kept if row[5] > 0)
    report.kept_refund_rows = sum(1 for row in kept if row[5] < 0)
    return kept, report


_SCHEMA = """
CREATE TABLE stores (store_id TEXT PRIMARY KEY, store_name TEXT, category TEXT, district TEXT);
CREATE TABLE products (product_id TEXT PRIMARY KEY, product_name TEXT,
                       product_category TEXT, unit_price REAL);
CREATE TABLE sales_clean (
    order_id TEXT, date TEXT, store_id TEXT, product_id TEXT,
    qty INTEGER, amount_cents INTEGER, payment TEXT, is_refund INTEGER
);
CREATE INDEX idx_clean_date ON sales_clean(date);
CREATE INDEX idx_clean_store ON sales_clean(store_id);
CREATE INDEX idx_clean_product ON sales_clean(product_id);
CREATE TABLE meta (key TEXT PRIMARY KEY, value TEXT);
"""


def build_clean_db(source: Path, target: Path) -> CleaningReport:
    """从只读的源库重建清洗表。返回清洗台账，供 `/api/health` 与数据质量面板使用。"""
    if not source.exists():
        raise FileNotFoundError("找不到源数据库：%s" % source)
    src = open_readonly(source)
    try:
        stores = [tuple(r) for r in src.execute("SELECT store_id, store_name, category, district FROM stores")]
        products = [
            tuple(r)
            for r in src.execute(
                "SELECT product_id, product_name, product_category, unit_price FROM products"
            )
        ]
        store_ids = {row[0] for row in stores}
        product_ids = {row[0] for row in products}
        rows, report = clean_rows(
            src.execute("SELECT order_id, date, store_id, product_id, qty, amount, payment FROM sales"),
            store_ids,
            product_ids,
        )
    finally:
        src.close()

    target.parent.mkdir(parents=True, exist_ok=True)
    if target.exists():
        target.unlink()
    out = sqlite3.connect(target)
    try:
        out.executescript(_SCHEMA)
        out.executemany("INSERT INTO stores VALUES (?,?,?,?)", stores)
        out.executemany("INSERT INTO products VALUES (?,?,?,?)", products)
        out.executemany("INSERT INTO sales_clean VALUES (?,?,?,?,?,?,?,?)", rows)
        out.execute(
            "INSERT INTO meta VALUES ('cleaning_report', ?)",
            (json.dumps(report.as_dict(), ensure_ascii=False),),
        )
        out.execute("INSERT INTO meta VALUES ('source_db', ?)", (source.name,))
        out.commit()
    finally:
        out.close()
    return report
