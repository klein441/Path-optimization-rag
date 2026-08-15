"""
工具注册表 — Agent 的确定性工具集

所有工具都复用现有"硬编码/规则"实现（费用计算、合约报价、时效查询等），
LLM 只能通过工具获取数据，禁止编造数字。每个工具提供：
- name / description（给 LLM 看的自然语言）
- parameters（JSON Schema）
- execute(args)（返回 {"ok": bool, "result": ...} 或 {"ok": False, "error": ...}）
"""
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import config
from knowledge_base import KnowledgeBase
from cost_calculator import CostCalculator
from llm_client import LLMClient
from retriever import get_retriever
import route_pricing
import db


class ToolContext:
    """共享运行上下文（惰性构建）"""

    _instance = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._ready = False
        return cls._instance

    def __init__(self):
        if self._ready:
            return
        self.kb = KnowledgeBase()
        self.kb.build()
        self.cost_calc = CostCalculator()
        self.llm = LLMClient()
        self.retriever = get_retriever()
        self._ready = True


class Tool:
    def __init__(self, name, description, parameters, execute_fn):
        self.name = name
        self.description = description
        self.parameters = parameters
        self._execute = execute_fn

    def execute(self, args):
        try:
            result = self._execute(args or {})
            return {"ok": True, "result": result}
        except Exception as e:
            return {"ok": False, "error": f"{self.name} 执行失败: {e}"}

    def to_dict(self):
        return {
            "name": self.name,
            "description": self.description,
            "parameters": self.parameters,
        }


class ToolRegistry:
    """工具注册与调用"""

    def __init__(self):
        self.ctx = ToolContext()
        self.tools = self._build()

    def _build(self):
        ctx = self.ctx
        return {
            "find_factories": Tool(
                "find_factories",
                "按产品类型和箱数（千支）匹配可发货工厂",
                {"product_type": "string", "glove_qty": "number", "glove_unit": "string"},
                lambda a: ctx.llm._find_factories_by_capacity(
                    a.get("product_type", ""), a.get("glove_qty", 0), a.get("glove_unit", "千支")),
            ),
            "top_origin_ports": Tool(
                "top_origin_ports",
                "查询目的港对应海运费最便宜的 Top5 起运港（含船公司、有效期）",
                {"dest_port": "string", "box_type": "string"},
                lambda a: ctx.llm._find_top_5_origin_ports(a.get("dest_port", ""), a.get("box_type", "40HQ")),
            ),
            "generate_candidates": Tool(
                "generate_candidates",
                "枚举 工厂 x 起运港 路线并计算全费用、时效、综合评分，返回候选方案列表",
                {"input_data": "object"},
                lambda a: ctx.llm._generate_candidates(a.get("input_data", {})),
            ),
            "calculate_cost": Tool(
                "calculate_cost",
                "计算指定路线的完整费用明细（陆运+港杂+海运+报关等）",
                {"input_data": "object", "factory": "string", "origin_port": "string",
                 "dest_port": "string", "trade_term": "string", "box_type": "string",
                 "contract_ocean_rate": "number"},
                lambda a: ctx.cost_calc.calculate(
                    a.get("input_data", {}), a.get("factory", ""), a.get("origin_port", ""),
                    a.get("dest_port", ""), a.get("trade_term", "FOB"), a.get("box_type", "40HQ"),
                    contract_ocean_rate=a.get("contract_ocean_rate", 0) or 0),
            ),
            "query_transit_time": Tool(
                "query_transit_time",
                "查询工厂到起运港的内陆运输时效（天数）",
                {"factory": "string", "origin_port": "string", "transport_mode": "string"},
                lambda a: route_pricing.query_land_transit_time(
                    a.get("factory", ""), a.get("origin_port", ""), a.get("transport_mode", "direct")),
            ),
            "query_land_freight": Tool(
                "query_land_freight",
                "查询工厂到起运港的拖车运费（含样本量）",
                {"factory": "string", "origin_port": "string", "transport_mode": "string", "box_type": "string"},
                lambda a: route_pricing.query_land_freight(
                    a.get("factory", ""), a.get("origin_port", ""),
                    a.get("transport_mode", "direct"), a.get("box_type", "40HQ")),
            ),
            "get_country_stats": Tool(
                "get_country_stats",
                "获取指定运抵国的历史统计（常用港、贸易条款、海运天数、费用中位数）",
                {"dest_country": "string"},
                lambda a: ctx.llm._get_data_stats(a.get("dest_country", "")),
            ),
            "retrieve_knowledge": Tool(
                "retrieve_knowledge",
                "在物流知识库（Excel 规则/报价/费率 + 结构化知识）中做混合检索",
                {"query": "string", "input_data": "object", "top_k": "number"},
                lambda a: ctx.retriever.retrieve(
                    query=a.get("query", ""), input_data=a.get("input_data", {}),
                    top_k=a.get("top_k", config.RETRIEVAL_TOP_K)),
            ),
            "check_fda": Tool(
                "check_fda",
                "检查运抵国是否需要 FDA 合规（目前仅美国需要）",
                {"dest_country": "string"},
                lambda a: a.get("dest_country", "") in config.FDA_COUNTRIES,
            ),
            "save_feedback": Tool(
                "save_feedback",
                "记录用户反馈（确认/改选/费用修正），用于自适应学习",
                {"log_id": "number", "user_action": "string", "chosen_factory": "string",
                 "chosen_port": "string", "delta_cost": "number", "note": "string"},
                lambda a: db.safe_save_feedback(
                    a.get("log_id"), a.get("user_action", ""), a.get("chosen_factory"),
                    a.get("chosen_port"), a.get("delta_cost"), a.get("note", "")),
            ),
        }

    def get(self, name):
        return self.tools.get(name)

    def list_tools(self):
        return [t.to_dict() for t in self.tools.values()]

    def execute(self, name, args=None):
        tool = self.tools.get(name)
        if not tool:
            return {"ok": False, "error": f"未知工具: {name}"}
        return tool.execute(args or {})


def get_tool_registry():
    return ToolRegistry()