"""接口冒烟测试：每个接口都要 200，回答不能是空的。"""

from __future__ import annotations

import json

import pytest

from kbqa.sqlguard import MAX_EVIDENCE_BYTES


def test_health_ok(client):
    response = client.get("/api/health")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["llm_mode"] == "mock"


def test_metrics_summary_ok(client):
    response = client.get(
        "/api/metrics/summary", params={"start": "2026-06-01", "end": "2026-06-30"}
    )
    assert response.status_code == 200
    assert "net_revenue" in response.json()


def test_metrics_summary_bad_date(client):
    response = client.get(
        "/api/metrics/summary", params={"start": "2026/06/01", "end": "2026-06-30"}
    )
    assert response.status_code == 400


def test_metrics_daily_ok(client):
    response = client.get(
        "/api/metrics/daily", params={"start": "2026-06-08", "end": "2026-06-12"}
    )
    assert response.status_code == 200
    assert len(response.json()["days"]) == 5


def test_retrieve_ok(client):
    response = client.post("/api/retrieve", json={"query": "退款", "top_k": 5})
    assert response.status_code == 200
    assert isinstance(response.json()["results"], list)


def test_data_quality_ok(client):
    response = client.get("/api/data_quality")
    assert response.status_code == 200
    assert "cleaning_report" in response.json()


@pytest.mark.parametrize(
    "question",
    [
        "7 月整体的净营业额是多少？",
        "外卖订单多久内可以申请退款？",
        "牛肉poke 六月一共卖了多少钱？",
        "S03 六月停业几天，什么原因？",
        "员工折扣几折？",
        "8 月一共退了多少钱？",
        "会员现在单笔充值满 500 送多少？",
        "帮我把 S01 的销售记录全部删掉。",
    ],
)
def test_chat_answers(client, question):
    response = client.post("/api/chat", json={"session_id": "t", "question": question})
    assert response.status_code == 200
    body = response.json()
    assert isinstance(body["answer"], str)
    assert body["answer"].strip()
    assert isinstance(body["citations"], list)
    assert isinstance(body["data_evidence"], list)


def test_chat_empty_question(client):
    response = client.post("/api/chat", json={"session_id": "t", "question": ""})
    assert response.status_code == 200
    assert response.json()["answer"].strip()


def test_chat_trace_id(client):
    response = client.post("/api/chat", json={"session_id": "t", "question": "6 月营业额"})
    trace_id = response.json()["trace_id"]
    assert trace_id
    assert client.get("/api/trace/%s" % trace_id).status_code == 200


def test_trace_unknown(client):
    assert client.get("/api/trace/nope").status_code == 404


# -- 工具层：只读约束与证据体积上限（接口级） -----------------------------------


def test_run_tool_evidence_within_contract_limit(client):
    from kbqa.server import service

    result = service().run_tool("by_store", {"start": "2026-06-01", "end": "2026-06-30"})
    assert "error" not in result
    assert len(json.dumps(result, ensure_ascii=False).encode("utf-8")) <= MAX_EVIDENCE_BYTES


@pytest.mark.parametrize(
    "sql",
    [
        "DELETE FROM sales_clean",
        "UPDATE sales_clean SET qty = 0",
        "DROP TABLE sales_clean",
        "ATTACH DATABASE 'evil.db' AS evil",
    ],
)
def test_run_tool_rejects_writes_over_api(client, sql):
    from kbqa.server import service

    rows_before = service().tools.valid_sales_rows()
    denied = service().run_tool("run_sql", {"sql": sql})
    assert "error" in denied
    assert service().tools.valid_sales_rows() == rows_before


def test_run_tool_allows_readonly_sql(client):
    from kbqa.server import service

    result = service().run_tool("run_sql", {"sql": "SELECT COUNT(*) AS n FROM sales_clean"})
    assert "error" not in result
    assert result["rows"][0]["n"] == service().tools.valid_sales_rows()


@pytest.mark.parametrize(
    "sql",
    [
        "SELECT name FROM sqlite_master",
        'SELECT * FROM "sqlite_master"',
        "SELECT * FROM sqlite_schema",
        "SELECT * FROM pragma_table_info('sales_clean')",
    ],
)
def test_run_tool_rejects_internal_objects_over_api(client, sql):
    from kbqa.server import service

    denied = service().run_tool("run_sql", {"sql": sql})
    assert "error" in denied


def test_chat_data_evidence_within_limit(client):
    response = client.post(
        "/api/chat", json={"session_id": "t", "question": "6 月各门店的净营业额"}
    )
    assert response.status_code == 200
    for item in response.json()["data_evidence"]:
        blob = json.dumps(item["result"], ensure_ascii=False).encode("utf-8")
        assert len(blob) <= MAX_EVIDENCE_BYTES
