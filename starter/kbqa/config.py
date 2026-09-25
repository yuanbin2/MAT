"""配置：路径、今天、大模型三件套，全部从环境变量读。

本地开发时可以把模型三件套写进仓库根的 `.env`（已被 .gitignore 忽略），
启动时自动补进环境变量，省得每次手敲。两点约定：

- **真实环境变量优先**：`.env` 只补 `os.environ` 里还没有的键，
  所以评测/预检脚本注入的 `LLM_*` 不会被本地 `.env` 覆盖。
- **可以整体关掉**：`ENV_FILE=`（空串或 `off`/`none`/`0`）表示一个字都不读，
  测试与 mock 演练靠它保证不受本地 `.env` 影响。
"""

from __future__ import annotations

import os
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date
from pathlib import Path

#: 契约规定：系统的“今天”固定为 2026-09-01。
#: 允许用环境变量覆盖，只为测试留一个口子，默认值就是契约值。
DEFAULT_TODAY = "2026-09-01"

PACKAGE_DIR = Path(__file__).resolve().parent
PROJECT_DIR = PACKAGE_DIR.parent

#: `ENV_FILE` 取这些值时跳过 .env（空串也算）。
_ENV_FILE_OFF = {"", "0", "off", "none", "no", "false"}

#: 默认查找的 .env：仓库根在前、starter/ 在后，后者可以覆盖前者的同名键。
_DEFAULT_ENV_FILES = (PROJECT_DIR.parent / ".env", PROJECT_DIR / ".env")

#: 由 .env 写进 os.environ 的键。真实环境变量（不在这个集合里的）永远优先。
_ENV_FROM_FILES: set[str] = set()


def _default_workspace() -> Path:
    """data/ 与 knowledge_base/ 在本项目的上一层。"""
    return PROJECT_DIR.parent


def _path_from_env(name: str, fallback: Path) -> Path:
    raw = os.environ.get(name)
    return Path(raw).expanduser().resolve() if raw else fallback.resolve()


def parse_env_file(text: str) -> dict[str, str]:
    """解析 .env 文本：支持 `#` 注释、空行、`export ` 前缀、单双引号、未加引号值的行内注释。"""
    values: dict[str, str] = {}
    for raw_line in (text or "").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[len("export ") :].lstrip()
        if "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        if not key:
            continue
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
            value = value[1:-1]
        elif " #" in value:
            value = value.split(" #", 1)[0].strip()
        values[key] = value
    return values


def env_files_to_load() -> list[Path]:
    """本次要从哪些 .env 读值。`ENV_FILE` 没设就是默认位置；设成 off 类值就一个都不读。"""
    raw = os.environ.get("ENV_FILE")
    if raw is None:
        return list(_DEFAULT_ENV_FILES)
    if raw.strip().lower() in _ENV_FILE_OFF:
        return []
    return [
        Path(item).expanduser()
        for item in raw.split(os.pathsep)
        if item.strip()
    ]


def load_env_files(files: Sequence[Path] | None = None) -> list[Path]:
    """把 .env 里的键补进 `os.environ`，返回实际读到的文件（不存在就跳过）。

    真实环境变量优先：只补 "os.environ 里本来没有、且不是上一轮由 .env 写进去的" 键。
    """
    protected = {key for key in os.environ if key not in _ENV_FROM_FILES}
    loaded: list[Path] = []
    for path in (files if files is not None else env_files_to_load()):
        if not path.is_file():
            continue
        try:
            text = path.read_text(encoding="utf-8-sig")
        except OSError:
            continue
        for key, value in parse_env_file(text).items():
            if key in protected:
                continue
            os.environ[key] = value
            _ENV_FROM_FILES.add(key)
        loaded.append(path)
    return loaded


@dataclass(frozen=True)
class Settings:
    data_dir: Path
    kb_dir: Path
    var_dir: Path
    today: date
    llm_base_url: str
    llm_api_key: str
    llm_model: str
    llm_timeout: float
    chat_budget: float

    @property
    def source_db(self) -> Path:
        return self.data_dir / "pos.db"

    @property
    def clean_db(self) -> Path:
        return self.var_dir / "clean.db"

    @property
    def index_path(self) -> Path:
        # 索引缓存跟着仓库走，clone 下来就能直接起服务，不用等建索引。
        #
        # INDEX_PATH 可以把它挪到别处：演练与测试**必须**用这个口子。
        # 否则临时知识库（比如新增了一篇文档的副本）重建出来的索引会覆盖
        # 仓库里跟踪的那份 .cache/index.json——历史上真的发生过，
        # 导致提交进仓库的索引与真实知识库对不上。
        override = os.environ.get("INDEX_PATH")
        if override:
            return Path(override).expanduser().resolve()
        return PROJECT_DIR / ".cache" / "index.json"

    @property
    def traces_dir(self) -> Path:
        """trace 落盘目录：有界、脱敏，随 var/ 一起被 gitignore。"""
        return self.var_dir / "traces"

    @property
    def live(self) -> bool:
        """契约 §7.2：没有 Key 就进入 mock 降级模式，服务照常启动。"""
        return bool(self.llm_api_key and self.llm_base_url and self.llm_model)

    @property
    def llm_mode(self) -> str:
        return "live" if self.live else "mock"


def load_settings() -> Settings:
    # 先把 .env 补进环境变量，后面照旧只读 os.environ——配置来源始终是环境变量。
    load_env_files()
    workspace = _default_workspace()
    return Settings(
        data_dir=_path_from_env("DATA_DIR", workspace / "data"),
        kb_dir=_path_from_env("KB_DIR", workspace / "knowledge_base"),
        var_dir=_path_from_env("VAR_DIR", PROJECT_DIR / "var"),
        today=date.fromisoformat(os.environ.get("TODAY", DEFAULT_TODAY)),
        # 地址原样使用：不补 /v1，不截路径（契约 §7.2）。
        llm_base_url=os.environ.get("LLM_BASE_URL", "").strip().rstrip("/"),
        llm_api_key=os.environ.get("LLM_API_KEY", "").strip(),
        llm_model=os.environ.get("LLM_MODEL", "").strip(),
        # 契约 §7.3：单次模型调用超时不小于 120 秒。
        llm_timeout=float(os.environ.get("LLM_TIMEOUT", "120")),
        # 契约 §7.3：/api/chat 整体在 180 秒内返回，这里留出余量。
        chat_budget=float(os.environ.get("CHAT_BUDGET", "150")),
    )
