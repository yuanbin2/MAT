"""测试夹具。

检索这块在测试里默认换成固定返回，这样测试就不用跟着知识库一起改，
跑起来也快。要看真实检索效果直接起服务问两句就行；
需要真实检索的用例用 `real_retriever` 夹具临时换回来。
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

# 测试不读仓库根的 .env：否则本机配了 Key 就会把测试带进 live 模式，
# 既慢又可能真的去请求付费模型。要测 .env 解析请直接调 parse_env_file/load_env_files。
os.environ["ENV_FILE"] = ""

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from kbqa import retriever as retriever_module  # noqa: E402

FAKE_TEXT = "退款政策 v2 > 三、时限：外卖订单在订单送达后 24 小时内可以申请退款。"

#: 在打桩之前先留一份真实实现，供 `real_retriever` 夹具还原。
_ORIGINAL_SEARCH = retriever_module.Retriever.search


def fake_search(self, query, top_k=5, **kwargs):
    hit = retriever_module.Hit(
        doc_id="KB-013",
        chunk_id="KB-013#1",
        score=42.0,
        text=FAKE_TEXT,
        source_text=FAKE_TEXT,
        meta={"title": "退款政策 v2", "status": "现行"},
    )
    return retriever_module.SearchResult(
        hits=[hit][:top_k],
        query=query,
        terms=[],
        expansions=[],
        filtered=[],
        coverage=1.0,
    )


@pytest.fixture(scope="session")
def client(tmp_path_factory):
    os.environ["VAR_DIR"] = str(tmp_path_factory.mktemp("var"))
    for key in ("LLM_BASE_URL", "LLM_API_KEY", "LLM_MODEL"):
        os.environ.pop(key, None)

    from fastapi.testclient import TestClient

    from kbqa import server

    retriever_module.Retriever.search = fake_search
    return TestClient(server.app)


@pytest.fixture()
def real_retriever():
    """临时把检索还原成真实实现（用于需要真实命中的用例）。"""
    retriever_module.Retriever.search = _ORIGINAL_SEARCH
    try:
        yield
    finally:
        retriever_module.Retriever.search = fake_search
