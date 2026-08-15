"""
查询路由器 — 自适应层入口

根据用户消息/表单参数判断意图与复杂度，决定：
- path: fast（快速路径）/ agent（Agent 多步）/ qa（纯知识问答）
- profile: 检索画像（top_k、检索源、是否多轮检索、是否查询扩展）
"""
import config

_COMPARE_KEYWORDS = ["对比", "比较", "哪个划算", "哪个便宜", "区别", "vs", "还是", "备选", "替代"]
_RECOMMEND_KEYWORDS = ["推荐", "发到", "发往", "从哪里", "从哪", "最划算", "划算", "便宜",
                       "哪家", "怎么走", "路线", "方案", "到港", "出口", "走哪个", "走哪"]
_URGENT_KEYWORDS = ["加急", "赶船期", "尽快", "越快越好", "urgent", "紧急"]
# 时效/时长咨询：问「到X多少天/多久/几天/时效」且没有具体发货需求时是知识咨询，
# 不应被「赶船期/加急」关键词拖进 urgent/agent 路径做候选生成与多轮重试。
_TIME_CONSULT_KEYWORDS = ("多少天", "几天", "多久", "多长时间", "需要多少天", "最快多久",
                          "海运天数", "到货时间", "要几天", "要多久", "时效")
_EXCEPTION_KEYWORDS = ["没查到", "无报价", "没有报价", "异常", "失败", "为什么", "查不到", "无匹配"]
_CONSULT_KEYWORDS = ["哪些工厂", "是什么", "什么意思", "介绍", "如何计算", "怎么算", "什么是",
                     "多少天", "有哪些", "知识", "解释", "help", "咨询"]

# 术语/概念解释：贸易条款类问题（即使含「区别/对比」也是概念问答，不是路线对比）
_TERM_CONCEPTS = ("fob", "ddp", "cif", "cfr", "fca", "exw", "dap", "贸易条款", "贸易术语", "incoterms", "贸易方式")
_EXPLAIN_KEYWORDS = ("区别", "解释", "什么是", "是什么", "含义", "介绍", "意思", "怎么理解", "讲讲", "干嘛", "作用", "包括", "包含")

_INTENT_BY_KEYWORD = [
    ("compare", _COMPARE_KEYWORDS),
    ("urgent", _URGENT_KEYWORDS),
    ("exception", _EXCEPTION_KEYWORDS),
    ("consult", _CONSULT_KEYWORDS),
]

_COMPLEXITY_TOP_K = {"low": 6, "medium": 8, "high": 14}


_VALID_INTENTS = {"standard_recommend", "natural_recommend", "compare", "urgent",
                   "exception", "consult", "follow_up"}
# follow_up 消息中若含这些指代词，视为引用上文的追问（无需 LLM 重新分类）
_REFERENCE_MARKERS = ("那", "这个", "这", "它", "上面", "刚才", "上一", "重新", "然后")
_INTENT_DESC = {
    "standard_recommend": "表单已填写完整、明确要求生成推荐方案",
    "natural_recommend": "用自然语言描述发货需求（产品/目的地/数量等），要求推荐路线",
    "compare": "比较多个港口/工厂/方案谁更划算或更快",
    "urgent": "加急、赶船期、要求尽快到货",
    "exception": "没查到、无报价、报错、质疑结果",
    "consult": "知识问答：工厂信息、贸易条款、港口、费用计算方式等解释",
    "follow_up": "追问、补充信息、引用上文的继续对话",
}


class QueryRouter:
    """查询理解与路由（关键词优先，意图模糊时可选 LLM 路由）"""

    def __init__(self, llm_client=None):
        self.llm = llm_client

    def classify(self, message="", input_data=None, session_id=None):
        input_data = input_data or {}
        message = str(message or "").strip()
        low = message.lower()

        # 0) 术语/概念解释优先 → consult（如「FOB和DDP有什么区别」「解释一下CIF」是概念问答，
        #    不应被「区别/对比」关键词误路由到 compare/agent 去生成货运推荐）
        intent = None
        if any(t in low for t in _TERM_CONCEPTS) and any(k in low for k in _EXPLAIN_KEYWORDS):
            intent = "consult"

        # 0.5) 时效/时长咨询优先 → consult：问「到美国多少天/多久/时效」且
        #      无具体发货需求（无 产品+目的港 信号）且表单未填完整时，是知识问答不是加急推荐，
        #      避免「赶船期到美国一般需要多少天？」被路由到 urgent/agent 空候选反复重试。
        if intent is None:
            _time_consult = any(k in low for k in _TIME_CONSULT_KEYWORDS)
            _shipment_signal = False
            try:
                from agent.extractor import PRODUCT_KEYWORDS, PORT_NAMES
                _shipment_signal = (
                    any(kw in low for kw, _ in PRODUCT_KEYWORDS)
                    and any(pt in message for pt in PORT_NAMES)
                )
            except Exception:
                _shipment_signal = False
            _form_complete = bool(
                input_data.get("destPort")
                and (input_data.get("gloveQty") or input_data.get("boxCount")))
            if _time_consult and not _shipment_signal and not _form_complete:
                intent = "consult"

        # 1) 关键词判定意图
        if intent is None:
            for name, keywords in _INTENT_BY_KEYWORD:
                if any(k.lower() in low for k in keywords):
                    intent = name
                    break

        # 2) 表单/输入信号修正
        if intent is None:
            urgent_flag = bool(input_data.get("urgent")) or bool(input_data.get("requiredArrival"))
            if urgent_flag:
                intent = "urgent"
            elif self._has_recommend_signal(message):
                intent = "natural_recommend"
            elif message and session_id:
                intent = "follow_up"
            elif message and not input_data.get("destCountry"):
                intent = "consult"
            else:
                intent = "standard_recommend"

        # 2.5) LLM 路由：关键词无法确定意图时，用 LLM 分类（模糊/非典型问法；
        #       follow_up 但消息长且不含指代词时也交给 LLM 判断）
        routed_by = "keyword"
        llm_confidence = None
        need_llm = intent is None or (
            intent == "follow_up" and len(message) >= 10
            and not any(m in message for m in _REFERENCE_MARKERS)
        )
        if config.LLM_ROUTING_ENABLED and config.LLM_ENABLED and message and len(message) >= 4 and need_llm:
            llm_route = self._classify_by_llm(message, input_data)
            if llm_route and llm_route.get("intent") in _VALID_INTENTS:
                intent = llm_route["intent"]
                routed_by = "llm"
                try:
                    llm_confidence = max(0.0, min(1.0, float(llm_route.get("confidence", 0.6))))
                except (TypeError, ValueError):
                    llm_confidence = 0.6

        # 3) 复杂度与路径
        complexity = self._complexity(intent, message, input_data)
        path = self._path(intent, complexity)

        # 4) 检索画像（自适应参数）
        profile = {
            "top_k": _COMPLEXITY_TOP_K.get(complexity, 8),
            "sources": ["structured", "keyword", "vector"],
            "multi_round": intent in ("exception", "compare"),
            "query_expansion": intent in ("exception", "consult"),
            "use_rerank": intent in ("compare",) or complexity == "high",
        }

        confidence = llm_confidence if routed_by == "llm" else (0.8 if intent else 0.5)
        return {
            "intent": intent,
            "complexity": complexity,
            "path": path,
            "profile": profile,
            "confidence": confidence,
            "routed_by": routed_by,
        }

    def _classify_by_llm(self, message, input_data):
        """LLM 意图分类（失败回退 None，调用方沿用关键词结果）"""
        try:
            if self.llm is None:
                from llm_client import LLMClient
                self.llm = LLMClient()
            import json
            system = ("你是物流路径优化系统的查询意图路由器。只输出 JSON："
                      '{"intent": "<意图>", "confidence": 0.0-1.0}。意图取值与含义：\n' +
                      "\n".join(f"- {k}: {v}" for k, v in _INTENT_DESC.items()))
            user = (f"用户消息：{message}\n\n表单字段（可能为空）："
                    f"{json.dumps(input_data, ensure_ascii=False)[:500]}")
            out = self.llm.llm_structured_call(system, user, temperature=0.0, max_tokens=200)
            if out and out.get("intent") in _VALID_INTENTS:
                print(f"[路由] LLM 分类: intent={out.get('intent')} confidence={out.get('confidence')}")
                return out
        except Exception as e:
            print(f"[路由] LLM 分类失败，回退关键词: {e}")
        return None

    def _has_recommend_signal(self, message):
        """消息是否含推荐意图信号（推荐词 / 产品 / 国家 / 港口）"""
        if not message:
            return False
        low = message.lower()
        if any(k in low for k in _RECOMMEND_KEYWORDS):
            return True
        try:
            from agent.extractor import PRODUCT_KEYWORDS, COUNTRY_KEYWORDS, PORT_NAMES
            for kw, _ in PRODUCT_KEYWORDS:
                if kw in low:
                    return True
            for name, _ in COUNTRY_KEYWORDS:
                if name in message:
                    return True
            for port in PORT_NAMES:
                if port in message:
                    return True
        except Exception:
            pass
        return False

    def _complexity(self, intent, message, input_data):
        if intent in ("compare", "exception"):
            return "high"
        if intent == "urgent":
            return "high" if input_data.get("requiredArrival") else "medium"
        if intent == "natural_recommend":
            return "high" if len(message) > 40 else "medium"
        if intent == "consult":
            return "low"
        if intent == "follow_up":
            return "medium"
        # standard_recommend
        if len(message) > 60:
            return "medium"
        return "low"

    def _path(self, intent, complexity):
        if intent == "consult":
            return "qa"
        if intent in ("natural_recommend", "compare", "urgent", "exception"):
            return "agent"
        if intent == "standard_recommend" and complexity == "low":
            return "fast" if config.AGENT_FASTPATH_ENABLED else "agent"
        if intent == "follow_up" and complexity == "medium":
            return "fast" if config.AGENT_FASTPATH_ENABLED else "agent"
        return "agent"


def classify(message="", input_data=None, session_id=None):
    """便捷入口"""
    return QueryRouter().classify(message=message, input_data=input_data, session_id=session_id)