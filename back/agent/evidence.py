"""证据评分器 — 答案级置信度与证据覆盖率

回答 Adaptive Agentic RAG 的两个关键问题：
1. 查几轮：证据覆盖率 / 置信度低于目标阈值时继续多轮检索（executor 收敛判据）；
2. 证据证明 + 人工交接：哪些结论有证据支撑（supported/missing），
   低置信时标记 needs_review（需人工复核），关键参数缺失时 requires_clarification（反问澄清）。
"""
import re
import config

_WS_RE = re.compile(r"\s+")
_PUNCT_RE = re.compile(r"[，。；、,.;:：/\\()（）\[\]【】\"'“”‘’|_\-]")
_CJK_RE = re.compile(r"[\u4e00-\u9fff]")


def _norm(s):
    """归一化：去空白与标点、转小写（用于子串匹配）"""
    s = str(s or "")
    s = _WS_RE.sub("", s)
    s = _PUNCT_RE.sub("", s)
    return s.lower()


# 中文虚词/疑问词字符：这类字组成的二元组（如「什么/区别/的和/有没有」）不要求检索文本中出现，
# 否则「FOB和DDP有什么区别」这类问题会因检索里没有「区别」二字被误判为证据不足。
_QA_STOP_CHARS = set(
    "的了吗呢啊和与或这那个有是不什么哪怎为何请问你我他它别之间还又再都并及被把"
    "从到往发要会能该将向由对于在上"
)


# 疑问/副词短语类 bigram（「多少/多久/一般/大概/需要/哪些…」）属于表达不是知识，
# 不要求检索文本中出现，否则「赶船期到美国一般需要多少天？」会因这些词未命中被判证据不足。
_QA_STOP_BIGRAMS = {
    "多少", "多久", "几天", "一般", "大概", "大约", "需要", "什么", "如何",
    "怎么", "为什么", "请问", "哪些", "还是", "或者", "应该", "能否", "能否", "可以",
    "时间", "多少天", "要多久", "要多长", "最快的", "怎么样", "怎么走", "哪个",
}


def _query_terms(text):
    """轻量分词：英文/数字词 + 中文双字 bigram（过滤虚词/疑问词，用于 QA 查询词覆盖率）"""
    text = str(text or "").lower()
    terms = re.findall(r"[a-z0-9]{2,}", text)
    cjk = _CJK_RE.findall(text)
    if len(cjk) >= 2:
        terms.extend(
            cjk[i] + cjk[i + 1]
            for i in range(len(cjk) - 1)
            if cjk[i] not in _QA_STOP_CHARS
            and cjk[i + 1] not in _QA_STOP_CHARS
            and (cjk[i] + cjk[i + 1]) not in _QA_STOP_BIGRAMS
        )
    return terms


def _mean(scores):
    scores = [float(s) for s in scores if s]
    return round(min(1.0, sum(scores) / len(scores)), 4) if scores else 0.0


def _reflect_ok(state):
    """取最近一次 reflect 判定的 ok（无则视为 True）"""
    for e in reversed(state.get("trace") or []):
        step = str(e.get("step", ""))
        if step.startswith("reflect"):
            return bool(e.get("ok", True))
    return True


class EvidenceScorer:
    """证据评分器（无状态，可直接调用）"""

    def score(self, state, mode=None):
        """计算证据分数

        :return: {mode, coverage, confidence, supported, missing,
                  retrieval_quality, determinism, needs_review, review_reason,
                  requires_clarification, clarify_question}
        """
        route = state.get("route") or {}
        mode = mode or ("qa" if route.get("path") == "qa" else "recommend")
        retrieval = state.get("retrieval") or []
        joined = "\n".join(str(c.get("text", "")) for c in retrieval)
        joined_norm = _norm(joined)

        if mode == "qa":
            return self._score_qa(state, joined_norm, retrieval)
        return self._score_recommend(state, joined_norm, retrieval)

    # ===== 推荐路径 =====
    def _score_recommend(self, state, joined_norm, retrieval):
        input_data = state.get("input") or {}
        result = state.get("result") or {}
        primary = result.get("primary") or {}
        candidates = state.get("candidates") or []

        def has(value):
            if value is None:
                return None
            v = _norm(value)
            return bool(v) and v in joined_norm

        checks = []  # (label, value, supported)

        factory = primary.get("factory") or primary.get("factoryShort") or primary.get("factory_short")
        origin = primary.get("departurePort") or primary.get("originPortCn")
        dest = primary.get("destPort")
        # 候选集也是确定性证据（规则/报价/费率生成），与检索文本合并后统一比对
        cand_parts = []
        for c in candidates:
            cand_parts.append(" ".join(str(c.get(k, "")) for k in (
                "factory", "factory_short", "origin_port", "dest_port",
                "box_type", "boxType", "shipping_line", "shippingLine",
                "carrier", "trade_term", "tradeTerm")))
        joined_all = joined_norm + "\n" + _norm("\n".join(cand_parts))

        def has_any(value):
            if value is None:
                return None
            v = _norm(value)
            return bool(v) and v in joined_all

        # 定位 primary 对应的候选（用于取箱型/船公司等增强字段）
        route_cand = None
        for c in candidates:
            if (str(c.get("factory", "")) == str(factory or "")
                    and str(c.get("origin_port", "")) == str(origin or "")
                    and str(c.get("dest_port", "")) == str(dest or "")):
                route_cand = c
                break

        if factory:
            checks.append(("工厂", factory, has_any(factory)))
        if origin:
            checks.append(("起运港", origin, has_any(origin)))
        if dest:
            checks.append(("目的港", dest, has_any(dest)))
        product = input_data.get("productType")
        if product:
            checks.append(("产品", product, has_any(product)))
        country = input_data.get("destCountry")
        if country:
            checks.append(("运抵国", country, has_any(country)))
        rc = route_cand or {}
        box = primary.get("boxType") or input_data.get("boxType") or rc.get("box_type") or rc.get("boxType")
        if box:
            checks.append(("箱型", box, has_any(box)))
        carrier = (primary.get("shippingLine") or primary.get("shipping_line")
                   or primary.get("carrier")
                   or rc.get("shipping_line") or rc.get("shippingLine"))
        if carrier:
            checks.append(("船公司", carrier, has_any(carrier)))
        if candidates:
            checks.append(("分配规则命中", "候选生成成功", True))
        cost = (primary.get("cost") or {}).get("total_cny")
        if cost is not None:
            route_match = route_cand is not None
            checks.append(("费用", f"{cost} CNY", route_match))

        total = len(checks)
        supported = [label for label, _, ok in checks if ok is True]
        missing = [label for label, _, ok in checks if ok is False]
        if not result.get("primary"):
            coverage = 0.0  # 无推荐结果 = 没有任何结论被证明
        else:
            coverage = round(len(supported) / total, 4) if total else 1.0

        quality = _mean(c.get("score") for c in retrieval[:8])
        source = str(result.get("source", ""))
        determinism = 1.0 if source in ("rule", "rule_engine") else (0.8 if source == "llm" else 0.5)
        ref_ok = _reflect_ok(state)
        confidence = round(
            0.55 * coverage + 0.25 * quality + 0.10 * determinism + 0.10 * (1 if ref_ok else 0), 3)

        needs_review = (
            not result.get("primary")
            or confidence < config.EVIDENCE_MIN_CONFIDENCE
            or coverage < config.EVIDENCE_TARGET_COVERAGE
        )
        reason_parts = []
        if not result.get("primary"):
            reason_parts.append("未生成推荐结果")
        if coverage < config.EVIDENCE_TARGET_COVERAGE and missing:
            reason_parts.append("结论缺乏证据支撑：" + "、".join(missing))
        if confidence < config.EVIDENCE_MIN_CONFIDENCE:
            reason_parts.append("综合置信度低于阈值")
        review_reason = "；".join(reason_parts) if reason_parts else (
            "结果证据覆盖率/置信度偏低，建议人工复核" if needs_review else "")

        requires_clarify, clarify_q = self._missing_input_question(input_data)

        return {
            "mode": "recommend",
            "coverage": coverage,
            "confidence": confidence,
            "supported": supported,
            "missing": missing,
            "retrieval_quality": quality,
            "determinism": source or "unknown",
            "needs_review": needs_review,
            "review_reason": review_reason,
            "requires_clarification": requires_clarify,
            "clarify_question": clarify_q,
        }

    # ===== 知识问答路径 =====
    def _score_qa(self, state, joined_norm, retrieval):
        message = state.get("message") or ""
        terms = _query_terms(message)
        if terms:
            coverage = round(sum(1 for t in terms if _norm(t) in joined_norm) / len(terms), 4)
        else:
            coverage = 1.0 if joined_norm else 0.0
        quality = _mean(c.get("score") for c in retrieval[:5])
        confidence = round(0.6 * coverage + 0.4 * quality, 3)

        # 覆盖率低 且 置信度低 才标记人工复核：口语化问法的内容 bigram 常无法逐字命中检索文本，
        # 若检索质量高、答案有据，不应误报「证据不足」。
        needs_review = coverage < 0.4 and confidence < 0.5
        review_reason = ("检索证据不足，回答可能不完整，建议人工核对。"
                         if needs_review else "")

        return {
            "mode": "qa",
            "coverage": coverage,
            "confidence": confidence,
            "supported": ["查询关键词命中检索证据"] if coverage >= 0.5 else [],
            "missing": ["查询关键词未在检索证据中命中"] if coverage < 0.5 else [],
            "retrieval_quality": quality,
            "determinism": "retrieval",
            "needs_review": needs_review,
            "review_reason": review_reason,
            "requires_clarification": False,
            "clarify_question": "",
        }

    # ===== 辅助 =====
    def _missing_input_question(self, input_data):
        """关键推荐参数缺失 -> 反问澄清"""
        missing = []
        if not input_data.get("destCountry"):
            missing.append("运抵国")
        if not input_data.get("destPort"):
            missing.append("目的港")
        if not (input_data.get("gloveQty") or input_data.get("boxCount")):
            missing.append("数量（箱数或千支）")
        if not missing:
            return False, ""
        return True, "请补充：" + "、".join(missing) + "，我再给出准确推荐。"


def score_evidence(state, mode=None):
    return EvidenceScorer().score(state, mode=mode)