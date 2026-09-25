"""`.env` 读取：解析规则、优先级、开关，以及"Key 不会入库"的守门测试。

测试默认不读仓库根的 .env（见 conftest：`ENV_FILE=""`），所以这里全部用临时文件，
不受本机真实配置影响。
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest

from kbqa import config

REPO = Path(__file__).resolve().parents[2]


@pytest.fixture(autouse=True)
def _clean_registry(monkeypatch):
    """每个用例一份干净的登记表，并在结束后把 `os.environ` 还原到用例开始前的样子。

    为什么不能只靠 `monkeypatch.delenv`：`load_env_files` 是**直接写 `os.environ`** 的，
    而 `monkeypatch.delenv` 只在键**本来就存在**时才留下撤销记录
    （见 `_pytest.monkeypatch.MonkeyPatch.delitem`：键不存在且 `raising=False` 时直接
    什么都不做）。于是"先 delenv 再被文件写回"的键在用例结束后会留在环境里——
    实测过一次后果：泄漏的 `LLM_API_KEY` 把后面的 `test_kb_drill` 和 hybrid trace 用例
    带进 live 模式，去请求真实模型然后失败。

    所以这里手写快照还原：用例期间新增的键删掉，原有的键恢复原值。
    """
    monkeypatch.setattr(config, "_ENV_FROM_FILES", set())
    saved = dict(os.environ)
    # 用例期间一律当作"本机没配 Key"，断言才稳定；结束后按快照还原。
    for key in ("LLM_BASE_URL", "LLM_API_KEY", "LLM_MODEL"):
        os.environ.pop(key, None)
    yield
    for key in [key for key in os.environ if key not in saved]:
        os.environ.pop(key, None)
    os.environ.update(saved)


# -- 解析 -------------------------------------------------------------------


def test_parse_env_file_handles_comments_quotes_and_export():
    text = """
# 整行注释
export A=1

B="hello world"
C='single quoted'
D=plain value
E=has # 行内注释
F=
   G   =   spaced   
"""
    assert config.parse_env_file(text) == {
        "A": "1",
        "B": "hello world",
        "C": "single quoted",
        "D": "plain value",
        "E": "has",
        "F": "",
        "G": "spaced",
    }


def test_parse_env_file_skips_lines_without_equals():
    assert config.parse_env_file("JUST_A_LINE\n=没有键\n\n# x") == {}


def test_parse_env_file_keeps_value_containing_equals():
    """值里带 = 不能被截断（Key 里并不常见，但 base64 之类会有）。"""
    assert config.parse_env_file("K=a=b=c") == {"K": "a=b=c"}


# -- 找哪些文件 --------------------------------------------------------------


def test_env_files_to_load_defaults_to_repo_root_then_starter(monkeypatch):
    monkeypatch.delenv("ENV_FILE", raising=False)
    assert config.env_files_to_load() == [
        REPO / ".env",
        REPO / "starter" / ".env",
    ]


@pytest.mark.parametrize("value", ["", "off", "OFF", "none", "0", "false", " no "])
def test_env_file_off_skips_everything(monkeypatch, value):
    monkeypatch.setenv("ENV_FILE", value)
    assert config.env_files_to_load() == []


def test_env_file_can_point_at_custom_paths(monkeypatch, tmp_path):
    a = tmp_path / "a.env"
    b = tmp_path / "b.env"
    monkeypatch.setenv("ENV_FILE", "%s%s%s" % (a, config.os.pathsep, b))
    assert config.env_files_to_load() == [a, b]


# -- 读值 -------------------------------------------------------------------


def test_load_env_files_fills_missing_keys(tmp_path, monkeypatch):
    path = tmp_path / ".env"
    path.write_text(
        "LLM_BASE_URL=https://example.test/v1\nLLM_API_KEY=sk-from-file\nLLM_MODEL=demo\n",
        encoding="utf-8",
    )

    assert config.load_env_files([path]) == [path]
    assert config.os.environ["LLM_API_KEY"] == "sk-from-file"
    settings = config.load_settings()
    assert settings.llm_mode == "live"
    assert settings.llm_base_url == "https://example.test/v1"
    assert settings.llm_model == "demo"


def test_real_env_var_wins_over_file(tmp_path, monkeypatch):
    """评测/预检脚本注入的环境变量必须压过本地 .env，否则预检会被本地配置带偏。"""
    monkeypatch.setenv("LLM_MODEL", "injected-model")
    path = tmp_path / ".env"
    path.write_text("LLM_MODEL=from-file\nLLM_API_KEY=sk-from-file\n", encoding="utf-8")

    config.load_env_files([path])
    assert config.os.environ["LLM_MODEL"] == "injected-model"
    assert config.os.environ["LLM_API_KEY"] == "sk-from-file"


def test_load_env_files_tolerates_missing_file(tmp_path):
    assert config.load_env_files([tmp_path / "nope.env"]) == []
    assert "LLM_API_KEY" not in config.os.environ


def test_later_file_overrides_earlier_one(tmp_path):
    """默认顺序是仓库根在前、starter/ 在后，后者可以覆盖前者。"""
    first = tmp_path / "root.env"
    second = tmp_path / "starter.env"
    first.write_text("LLM_MODEL=root\n", encoding="utf-8")
    second.write_text("LLM_MODEL=starter\n", encoding="utf-8")

    config.load_env_files([first, second])
    assert config.os.environ["LLM_MODEL"] == "starter"


def test_off_switch_keeps_service_in_mock(tmp_path, monkeypatch):
    """ENV_FILE= 时即使 .env 就在默认位置，也不能被读进来（mock 演练靠这个）。"""
    monkeypatch.setenv("ENV_FILE", "")
    monkeypatch.setattr(config, "_DEFAULT_ENV_FILES", (tmp_path / ".env",))
    (tmp_path / ".env").write_text("LLM_API_KEY=sk-should-not-load\n", encoding="utf-8")

    assert config.load_settings().llm_mode == "mock"
    assert "LLM_API_KEY" not in config.os.environ


# -- 守门：用例之间不能互相污染 -------------------------------------------------


def test_leak_guard_writes_env_from_file(tmp_path):
    """故意把文件里的值写进环境变量，交给下一个用例检查是否留痕。"""
    path = tmp_path / ".env"
    path.write_text("LLM_API_KEY=sk-leaked-value\n", encoding="utf-8")
    config.load_env_files([path])
    assert config.os.environ["LLM_API_KEY"] == "sk-leaked-value"


def test_leak_guard_next_case_sees_nothing():
    """上一个用例写进 os.environ 的值不能留下来。

    这是真实踩过的坑：`load_env_files` 直接写 os.environ，而 `monkeypatch.delenv`
    对"本来不存在的键"不留撤销记录，于是泄漏的 Key 把后面的用例带进 live 模式。
    """
    assert config.os.environ.get("LLM_API_KEY") != "sk-leaked-value"
    assert config.load_settings().llm_mode == "mock"


# -- 守门：Key 不会进仓库 ----------------------------------------------------


def _git_check_ignore(rel: str) -> bool:
    proc = subprocess.run(
        ["git", "check-ignore", "-q", rel],
        cwd=str(REPO),
        capture_output=True,
        text=True,
    )
    if proc.returncode not in (0, 1):
        pytest.skip("当前环境没有可用的 git")
    return proc.returncode == 0


def test_env_is_ignored_but_example_is_tracked():
    if not (REPO / ".git").exists():
        pytest.skip("不是 git 检出，跳过")
    assert _git_check_ignore(".env"), ".env 必须被 .gitignore 忽略，否则 Key 会入库"
    assert not _git_check_ignore(".env.example"), ".env.example 必须能入库（只放占位值）"
