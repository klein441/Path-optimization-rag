"""反馈闭环调权 — 基于 recommendation_feedback 表学习权重

数据来源（用户反馈动作）：
- confirm            用户确认推荐 -> 该工厂/起运港正向加分
- switch_alternative 用户改选其他工厂/港口 -> 改选目标加分、原推荐轻微减分
- modify             用户修正费用（delta_cost 为负表示实际更便宜）-> 修正该路由费用

权重应用：
- FEEDBACK_AUTO_APPLY=true 时，运行时自动加载缓存并调整候选 score / cost（在排序前注入）
- 缓存文件 config.FEEDBACK_WEIGHTS_CACHE（默认 data/feedback_weights.json）
- 离线重算：python back/scripts/apply_feedback_weights.py
"""
import json
import os
import time

import config
from db import fetch_feedback_rows, get_feedback_max_id


def _route_key(factory, port):
    return f"{str(factory or '').strip()}||{str(port or '').strip()}"


class FeedbackWeights:
    """反馈权重（可序列化/加载）"""

    def __init__(self, data=None):
        self.max_id = 0
        self.updated_at = None
        self.route_adjust = {}   # key -> {"score_bonus", "delta_mean", "count"}
        self.factory_boost = {}  # factory -> bonus
        self.port_boost = {}     # port -> bonus
        if data:
            self.load_dict(data)

    # ===== 计算 =====
    def compute(self, rows):
        route_score = {}
        route_delta = {}
        factory_score = {}
        port_score = {}
        for row in rows:
            action = str(row.get("user_action") or "")
            chosen_factory = str(row.get("chosen_factory") or "").strip()
            chosen_port = str(row.get("chosen_port") or "").strip()
            orig_factory = str(row.get("primary_factory") or "").strip()
            orig_port = str(row.get("primary_origin_port") or "").strip()
            delta = row.get("delta_cost")
            if delta is not None:
                try:
                    delta = float(delta)
                except (TypeError, ValueError):
                    delta = None

            if action == "confirm":
                if orig_factory:
                    factory_score[orig_factory] = factory_score.get(orig_factory, 0) + 1
                if orig_port:
                    port_score[orig_port] = port_score.get(orig_port, 0) + 1
                if orig_factory and orig_port:
                    k = _route_key(orig_factory, orig_port)
                    route_score[k] = route_score.get(k, 0) + 1
            elif action in ("switch_alternative", "modify"):
                # 改选目标加分
                if chosen_factory:
                    factory_score[chosen_factory] = factory_score.get(chosen_factory, 0) + 1
                if chosen_port:
                    port_score[chosen_port] = port_score.get(chosen_port, 0) + 1
                if chosen_factory and chosen_port:
                    k = _route_key(chosen_factory, chosen_port)
                    route_score[k] = route_score.get(k, 0) + 1
                # 原推荐轻微减分
                if orig_factory:
                    factory_score[orig_factory] = factory_score.get(orig_factory, 0) - 0.5
                if orig_port:
                    port_score[orig_port] = port_score.get(orig_port, 0) - 0.5
                # 费用修正（作用于原推荐路由）
                if delta is not None and orig_factory and orig_port:
                    k = _route_key(orig_factory, orig_port)
                    cur = route_delta.setdefault(k, [0.0, 0])
                    cur[0] += delta
                    cur[1] += 1

        route_adjust = {}
        for k, n in route_score.items():
            route_adjust[k] = {"score_bonus": round(min(10.0, n * 2.0), 2),
                               "delta_mean": 0.0, "count": int(n)}
        for k, (total, n) in route_delta.items():
            entry = route_adjust.setdefault(k, {"score_bonus": 0.0, "delta_mean": 0.0, "count": 0})
            entry["delta_mean"] = round(total / n, 2)
            entry["count"] += n

        self.route_adjust = route_adjust
        self.factory_boost = {k: round(min(10.0, v * 1.5), 2) for k, v in factory_score.items() if v}
        self.port_boost = {k: round(min(10.0, v * 1.5), 2) for k, v in port_score.items() if v}
        return self

    # ===== 应用 =====
    def adjust_candidates(self, candidates):
        """按反馈权重调整候选评分/费用（原地修改并返回）"""
        if not self.enabled:
            return candidates
        for c in candidates:
            factory = str(c.get("factory", "") or "")
            port = str(c.get("origin_port", "") or "")
            bonus = self.factory_boost.get(factory, 0.0) + self.port_boost.get(port, 0.0)
            adj = self.route_adjust.get(_route_key(factory, port))
            fb = {}
            if adj:
                bonus += adj["score_bonus"]
                if adj["delta_mean"] and isinstance(c.get("cost"), dict):
                    c["cost"]["total_cny"] = round(c["cost"].get("total_cny", 0) + adj["delta_mean"], 2)
                    fb["delta_cny"] = adj["delta_mean"]
                fb["count"] = adj["count"]
            if bonus:
                c["score"] = round(float(c.get("score", 0)) + min(10.0, bonus), 1)
                fb["score_bonus"] = round(min(10.0, bonus), 2)
            if fb:
                c.setdefault("feedback", {}).update(fb)
        return candidates

    # ===== 序列化 =====
    def to_dict(self):
        return {
            "max_id": self.max_id,
            "updated_at": self.updated_at,
            "route_adjust": self.route_adjust,
            "factory_boost": self.factory_boost,
            "port_boost": self.port_boost,
        }

    def load_dict(self, d):
        self.max_id = int(d.get("max_id", 0) or 0)
        self.updated_at = d.get("updated_at")
        self.route_adjust = d.get("route_adjust") or {}
        self.factory_boost = d.get("factory_boost") or {}
        self.port_boost = d.get("port_boost") or {}
        return self

    @property
    def enabled(self):
        return bool(self.route_adjust or self.factory_boost or self.port_boost)


def compute_weights(rows):
    return FeedbackWeights().compute(rows)


def load_weights():
    """加载缓存权重；反馈表有新数据时自动重算"""
    cache = config.FEEDBACK_WEIGHTS_CACHE
    data = None
    if os.path.exists(cache):
        try:
            with open(cache, encoding="utf-8") as f:
                data = json.load(f)
        except Exception:
            data = None
    max_id = get_feedback_max_id()
    if data and int(data.get("max_id", 0) or 0) >= max_id:
        return FeedbackWeights(data=data)
    rows = fetch_feedback_rows()
    fw = FeedbackWeights().compute(rows)
    fw.max_id = max_id
    fw.updated_at = time.strftime("%Y-%m-%d %H:%M:%S")
    try:
        os.makedirs(os.path.dirname(cache), exist_ok=True)
        with open(cache, "w", encoding="utf-8") as f:
            json.dump(fw.to_dict(), f, ensure_ascii=False, indent=2)
        print(f"[反馈调权] 权重已重算并写入缓存: {cache} (feedback max_id={max_id})")
    except Exception as e:
        print(f"[反馈调权] 写入缓存失败: {e}")
    return fw


_singleton = None
_singleton_at = 0.0


def get_feedback_weights(ttl=60):
    """运行时获取权重（带 TTL 缓存，避免每次请求查库）"""
    global _singleton, _singleton_at
    now = time.time()
    if _singleton is None or now - _singleton_at > ttl:
        _singleton = load_weights()
        _singleton_at = now
    return _singleton