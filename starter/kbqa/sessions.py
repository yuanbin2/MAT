"""对话历史，按 session_id 隔离。"""

from __future__ import annotations

import threading
from typing import Optional

MAX_TURNS = 6
MAX_SESSIONS = 500


class SessionStore:
    """每个会话独立保存最近几轮对话，够解追问就行，不同 session 之间不串线。"""

    def __init__(self, max_sessions: int = MAX_SESSIONS, max_turns: int = MAX_TURNS) -> None:
        self._sessions: dict[str, list[dict]] = {}
        self._lock = threading.Lock()
        self.max_sessions = max_sessions
        self.max_turns = max_turns

    def history(self, session_id: Optional[str]) -> list[dict]:
        if not session_id:
            return []
        with self._lock:
            return list(self._sessions.get(session_id, []))

    def append(self, session_id: Optional[str], turn: dict) -> None:
        if not session_id:
            return
        with self._lock:
            turns = self._sessions.setdefault(session_id, [])
            turns.append(turn)
            del turns[: max(0, len(turns) - self.max_turns)]
            # 会话数上限：清掉最早建立的会话，避免内存无限增长。
            while len(self._sessions) > self.max_sessions:
                oldest = next(iter(self._sessions))
                del self._sessions[oldest]

    def clear(self) -> None:
        with self._lock:
            self._sessions.clear()
