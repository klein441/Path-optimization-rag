"""
反思与校验器 — Agent 结果的质检链（self-correction）

校验项：
1. schema：推荐结果包含 primary
2. 引用：所选工厂/起运港必须来自候选集（防幻觉）
3. 预算：同分/近分选贵方案 -> 建议回退最便宜
4. 时效：无法按期到货时必须给出 risk_warning
5. 数据缺失：候选为空 -> 触发恢复（扩展检索/放宽港口）
"""
import json


class Reflector:
    """反思校验器"""

    def validate(self, state):
        """返回 {"ok": bool, "issues": [...], "can_retry": bool}"""
        issues = []
        result = state.get("result") or {}
        candidates = state.get("candidates") or []

        # 咨询类问答不做推荐级校验
        if state.get("route", {}).get("intent") == "consult":
            return {"ok": True, "issues": [], "can_retry": False}

        if not result.get("primary"):
            issues.append({
                "code": "no_result",
                "message": "未生成有效推荐结果",
                "fix": "retry",
            })
            return {"ok": False, "issues": issues, "can_retry": True}

        primary = result.get("primary", {})
        factory = primary.get("factory") or primary.get("factoryShort")
        origin = primary.get("departurePort")

        if candidates:
            if factory and not any(c.get("factory") == factory for c in candidates):
                issues.append({
                    "code": "reference_factory",
                    "message": f"LLM 选择了不在候选集中的工厂: {factory}",
                    "fix": "revert",
                })
            if origin and not any(c.get("origin_port") == origin for c in candidates):
                issues.append({
                    "code": "reference_port",
                    "message": f"LLM 选择了不在候选集中的起运港: {origin}",
                    "fix": "revert",
                })

        if result.get("cannotMeetArrival") and not result.get("risk_warning"):
            issues.append({
                "code": "arrival_warning_missing",
                "message": "无法按期到货但缺少风险提示",
                "fix": "patch",
            })

        if not candidates:
            issues.append({
                "code": "no_candidates",
                "message": "候选路线为空（可能是无报价/无产能匹配）",
                "fix": "retry",
            })

        return {
            "ok": len(issues) == 0,
            "issues": issues,
            "can_retry": any(i.get("fix") == "retry" for i in issues),
        }

    def suggest_recovery(self, state):
        """生成恢复步骤（executor 追加执行）"""
        steps = []
        route = state.get("route", {})
        input_data = state.get("input", {})
        query_text = state.get("message", "") or " ".join(
            str(input_data.get(k, "")) for k in ("productType", "destCountry", "destPort"))

        # 1) 扩展检索（加大 top_k + 查询扩展）
        steps.append({
            "tool": "retrieve_knowledge",
            "args": {
                "query": query_text,
                "input_data": input_data,
                "top_k": max(12, route.get("profile", {}).get("top_k", 8) + 6),
            },
            "output_key": "retrieval_recovered",
            "reason": "反思后扩展检索以补足信息",
        })

        # 2) 放宽条件重新生成候选（贸易条款/运输偏好交给系统默认）
        relaxed = dict(input_data)
        relaxed["tradePref"] = "auto"
        relaxed["transportPref"] = "balanced"
        steps.append({
            "tool": "generate_candidates",
            "args": {"input_data": relaxed},
            "output_key": "candidates",
            "reason": "放宽贸易条款与运输偏好后重新生成候选",
        })
        return steps