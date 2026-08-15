"""
规划器 — 把请求展开为工具调用序列（Plan）

不同意图对应不同执行计划；执行器（executor）按计划逐步调用工具，
并在反思（reflector）不通过时追加恢复步骤。
"""


class Planner:
    """基于意图的规则规划器"""

    def build_plan(self, state):
        route = state["route"]
        intent = route["intent"]
        input_data = state["input"]
        query_text = self._query_text(state)

        steps = [
            {
                "tool": "retrieve_knowledge",
                "args": {"query": query_text, "input_data": input_data, "top_k": route["profile"].get("top_k", 8)},
                "output_key": "retrieval",
                "reason": "检索相关知识（规则/报价/费率/结构化知识）",
            }
        ]

        if intent in ("standard_recommend", "natural_recommend", "urgent", "compare", "follow_up", "exception"):
            steps.append({
                "tool": "generate_candidates",
                "args": {"input_data": input_data},
                "output_key": "candidates",
                "reason": "枚举工厂x起运港候选路线并计算费用/时效/评分",
            })
            if intent == "compare":
                steps.append({
                    "tool": "get_country_stats",
                    "args": {"dest_country": input_data.get("destCountry", "")},
                    "output_key": "country_stats",
                    "reason": "获取运抵国统计用于对比分析",
                })
            if intent == "urgent":
                steps.append({
                    "tool": "query_transit_time",
                    "args": {"factory": "", "origin_port": ""},
                    "output_key": "transit",
                    "reason": "核对内陆时效（候选生成后会再校验交期）",
                })

        return steps

    @staticmethod
    def _query_text(state):
        """构造检索查询文本：消息 + 结构化字段"""
        parts = []
        msg = state.get("message", "")
        if msg:
            parts.append(msg)
        d = state["input"]
        for key, label in [("productType", "产品"), ("destCountry", "运抵国"), ("destPort", "目的港")]:
            if d.get(key):
                parts.append(f"{label}: {d[key]}")
        if d.get("transportPref"):
            parts.append(f"运输偏好: {d['transportPref']}")
        if d.get("tradePref"):
            parts.append(f"贸易条款: {d['tradePref']}")
        return " ".join(parts) or "物流 推荐"


def get_planner():
    return Planner()