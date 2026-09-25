"""Makefile 的模型配置语义：用**真实的 make 命令**验证，而不是照着 Makefile 推理。

守的是这条教训（DEBUG_LOG D30）：`export FOO` 在 FOO 未定义时会把 FOO 导出成**空串**，
而空串在配置里是有语义的——`ENV_FILE=` 表示"一个 .env 都不读"，
`LLM_API_KEY=` 会盖掉 .env 里的值。于是仓库根放着有效 .env，`make run` 依旧是 mock。

没装 make 时这些用例会 skip（CI 的 ubuntu 自带 make），也可以用 `MAKE_BIN=/path/to/make` 指定。
"""

from __future__ import annotations

import json
import os
import shutil
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
STARTER = REPO / "starter"

#: 允许用系统里的 make，也允许用 MAKE_BIN 显式指定便携版。
MAKE = os.environ.get("MAKE_BIN") or shutil.which("make") or shutil.which("mingw32-make")

pytestmark = pytest.mark.skipif(
    not MAKE, reason="未找到 make（装一个，或用 MAKE_BIN=/path/to/make 指定）"
)

#: 测试用的假配置——绝不能用真 Key。
FAKE_ENV = (
    "LLM_BASE_URL=https://api.example.test/v1\n"
    "LLM_API_KEY=sk-fake-for-makefile-test\n"
    "LLM_MODEL=fake-model\n"
)

#: 会干扰结果、必须从子进程环境里清掉的本项目变量。
_MANAGED_KEYS = (
    "ENV_FILE",
    "LLM_BASE_URL",
    "LLM_API_KEY",
    "LLM_MODEL",
    "DATA_DIR",
    "KB_DIR",
    "VAR_DIR",
)


def _clean_env(**extra: str | None) -> dict[str, str]:
    """干净的子进程环境；值为 None 的键直接删掉，' ' 之外的空串按原样保留。"""
    env = dict(os.environ)
    for key in _MANAGED_KEYS:
        env.pop(key, None)
    env.update({key: value for key, value in extra.items() if value is not None})
    return env


def _make_env(mkdir: Path, args: list[str], env: dict[str, str]) -> subprocess.CompletedProcess:
    return subprocess.run(
        [MAKE, *args, "PY=%s" % sys.executable],
        cwd=str(mkdir),
        env=env,
        capture_output=True,
        text=True,
        timeout=180,
    )


def _mode_from(stdout: str) -> str:
    for line in stdout.splitlines():
        if line.startswith("llm_mode="):
            return line.split("=", 1)[1].strip()
    raise AssertionError("输出里没有 llm_mode=：\n%s" % stdout)


def _copy_starter(tmp_path: Path) -> Path:
    """把 Makefile 与 kbqa/ 复制到临时目录。

    这样 `.env` 的查找位置（仓库根 + starter/）落在临时目录里，
    测试既能造"有理 .env"也能造"完全没有配置"，不会碰到真实仓库的 .env。
    """
    dst = tmp_path / "starter"
    dst.mkdir()
    shutil.copy(STARTER / "Makefile", dst / "Makefile")
    shutil.copytree(
        STARTER / "kbqa",
        dst / "kbqa",
        ignore=shutil.ignore_patterns("__pycache__"),
    )
    return dst


def _free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def _wait_mode(port: int, timeout: float = 60.0) -> str:
    deadline = time.time() + timeout
    last = ""
    while time.time() < deadline:
        try:
            with urllib.request.urlopen(
                "http://127.0.0.1:%d/api/health" % port, timeout=3
            ) as resp:
                return json.loads(resp.read().decode("utf-8"))["llm_mode"]
        except (urllib.error.URLError, OSError, KeyError, ValueError) as exc:
            last = str(exc)
            time.sleep(1)
    raise AssertionError("服务没起来（%s），最后错误：%s" % (port, last))


def _start_make_server(directory: Path, target: str, port: int, env: dict[str, str]):
    """后台跑 `make <target> PORT=...`，返回 Popen（调用方负责 _stop）。"""
    return subprocess.Popen(
        [MAKE, target, "PORT=%d" % port, "PY=%s" % sys.executable],
        cwd=str(directory),
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )


def _stop(proc: subprocess.Popen) -> None:
    if proc.poll() is not None:
        return
    if os.name == "nt":
        # /T 连同 make 的子进程（uvicorn）一起收掉
        subprocess.run(
            ["taskkill", "/F", "/T", "/PID", str(proc.pid)],
            capture_output=True,
            check=False,
        )
    else:
        proc.terminate()
    try:
        proc.wait(timeout=20)
    except subprocess.TimeoutExpired:  # pragma: no cover - 兜底
        proc.kill()


# -- 不启服务：直接看配置推导出的模式 ---------------------------------------


def test_valid_env_file_makes_run_live(tmp_path):
    """有效 .env + 系统未设三件套 → live（这正是回归前的失败场景）。"""
    starter = _copy_starter(tmp_path)
    (tmp_path / ".env").write_text(FAKE_ENV, encoding="utf-8")

    result = _make_env(starter, ["env-mode"], _clean_env())
    assert result.returncode == 0, result.stdout + result.stderr
    assert _mode_from(result.stdout) == "live", result.stdout


def test_no_config_at_all_is_mock(tmp_path):
    """既没有 .env 也没有系统变量 → mock。"""
    starter = _copy_starter(tmp_path)

    result = _make_env(starter, ["env-mode"], _clean_env())
    assert result.returncode == 0, result.stdout + result.stderr
    assert _mode_from(result.stdout) == "mock", result.stdout


def test_run_mock_beats_env_file_and_system_vars(tmp_path):
    """系统已设三件套 + 仓库还有有效 .env → run-mock 仍必须 mock。"""
    starter = _copy_starter(tmp_path)
    (tmp_path / ".env").write_text(FAKE_ENV, encoding="utf-8")
    env = _clean_env(
        LLM_BASE_URL="https://api.example.test/v1",
        LLM_API_KEY="sk-fake-system",
        LLM_MODEL="fake-model",
    )

    result = _make_env(starter, ["env-mode-mock"], env)
    assert result.returncode == 0, result.stdout + result.stderr
    assert _mode_from(result.stdout) == "mock", result.stdout


def test_system_vars_are_still_exported(tmp_path):
    """反向确认没有矫枉过正：外部真设了 ENV_FILE 时必须原样传下去。"""
    starter = _copy_starter(tmp_path)
    env_file = tmp_path / "explicit.env"
    env_file.write_text(FAKE_ENV, encoding="utf-8")

    result = _make_env(starter, ["env-mode"], _clean_env(ENV_FILE=str(env_file)))
    assert result.returncode == 0, result.stdout + result.stderr
    assert _mode_from(result.stdout) == "live", result.stdout


# -- 启真实服务：make run / make run-mock -----------------------------------


def test_make_run_serves_live(tmp_path):
    starter = _copy_starter(tmp_path)
    env_file = tmp_path / "explicit.env"
    env_file.write_text(FAKE_ENV, encoding="utf-8")
    port = _free_port()
    # 用真实数据与索引，只把 .env 指到临时文件——不碰仓库里的 .env。
    env = _clean_env(
        ENV_FILE=str(env_file),
        DATA_DIR=str(REPO / "data"),
        KB_DIR=str(REPO / "knowledge_base"),
        VAR_DIR=str(STARTER / "var"),
    )
    proc = _start_make_server(starter, "run", port, env)
    try:
        assert _wait_mode(port) == "live"
    finally:
        _stop(proc)


def test_make_run_mock_serves_mock_despite_system_vars(tmp_path):
    starter = _copy_starter(tmp_path)
    env_file = tmp_path / "explicit.env"
    env_file.write_text(FAKE_ENV, encoding="utf-8")
    port = _free_port()
    env = _clean_env(
        ENV_FILE=str(env_file),
        LLM_BASE_URL="https://api.example.test/v1",
        LLM_API_KEY="sk-fake-system",
        LLM_MODEL="fake-model",
        DATA_DIR=str(REPO / "data"),
        KB_DIR=str(REPO / "knowledge_base"),
        VAR_DIR=str(STARTER / "var"),
    )
    proc = _start_make_server(starter, "run-mock", port, env)
    try:
        assert _wait_mode(port) == "mock"
    finally:
        _stop(proc)
