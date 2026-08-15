"""会话记忆 — 按 sessionId 保存多轮上下文

- params: 最近确认/抽取的结构化参数（作为后续轮的默认值，当前消息/表单优先）
- history: 最近 N 轮问题摘要
- last_result: 上一轮推荐结果摘要（供 follow_up / QA 引用）
- TTL 自动清理
"""
import time

import config

_ALLOWED_PARAM_KEYS = {
    "productType", "destCountry", "destPort", "gloveQty", "gloveUnit",
    "boxCount", "boxType", "weight", "volume", "transportPref", "tradePref",
}


class SessionStore:
    """内存会话存储（单例）"""

    _instance = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._sessions = {}
            cls._instance._last_touch = 0.0
        return cls._instance

    def __init__(self):
        pass

    def get(self, session_id):
        if not session_id:
            return None
        self._cleanup()
        s = self._sessions.get(session_id)
        if s:
            s["last_seen"] = time.time()
        return s

    def update(self, session_id, params, message, result=None):
        """写入一轮会话；返回会话 dict"""
        if not session_id:
            return None
        self._cleanup()
        s = self._sessions.setdefault(session_id, {
            "params": {}, "history": [], "last_result": None,
            "created": time.time(), "last_seen": time.time(),
        })
        s["last_seen"] = time.time()
        if params:
            clean = {k: v for k, v in params.items()
                     if k in _ALLOWED_PARAM_KEYS and v not in (None, "")}
            s["params"].update(clean)
            s["params"] = {k: v for k, v in s["params"].items()
                           if k in _ALLOWED_PARAM_KEYS and v not in (None, "")}
        if message:
            s["history"].append({"q": message})
            s["history"] = s["history"][-config.SESSION_MAX_TURNS:]
        summary = self._summarize_result(result)
        if summary:
            s["last_result"] = summary
        return s

    def _summarize_result(self, result):
        primary = (result or {}).get("primary") or {}
        if not primary:
            return None
        return {
            "factory": primary.get("factory") or primary.get("factoryShort") or "",
            "origin": primary.get("departurePort") or "",
            "dest": primary.get("destPort") or "",
            "cost_cny": (primary.get("cost") or {}).get("total_cny"),
            "days": (primary.get("timeline") or {}).get("total_days"),
            "intent": ((result or {}).get("route") or {}).get("intent", ""),
        }

    def _cleanup(self):
        now = time.time()
        if now - self._last_touch < 60:
            return
        self._last_touch = now
        expired = [sid for sid, s in self._sessions.items()
                   if now - s.get("last_seen", 0) > config.SESSION_TTL]
        for sid in expired:
            self._sessions.pop(sid, None)


def get_session_store():
    return SessionStore()