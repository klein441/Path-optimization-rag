"""
推荐引擎 — 整合知识库、费用计算器、LLM客户端的统一推荐入口
"""
from llm_client import LLMClient
from knowledge_base import KnowledgeBase
from cost_calculator import CostCalculator
from config import LLM_ENABLED


class RecommendationEngine:
    """
    推荐引擎 — 统一入口
    整合：8张数据表 → 知识库 → 费用计算 → LLM推荐/规则引擎
    """

    _instance = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._initialized = False
        return cls._instance

    def __init__(self):
        if self._initialized:
            return
        self.kb = KnowledgeBase()
        self.kb.build()
        self.cost_calc = CostCalculator()
        self.llm_client = LLMClient()
        self._initialized = True

    def recommend(self, input_data):
        """
        生成物流路径推荐方案

        :param input_data: dict containing:
            - productType: 产品类型 (丁腈手套/PVC手套/PE产品/轮椅/小日化产品)
            - destCountry: 运抵国
            - boxCount: 箱数
            - weight: 重量(kg)
            - volume: 体积(CBM)
            - cargoReady: 货好时间 (ISO格式)
            - shipSchedule: 期望船期 (ISO格式)
            - transportPref: 运输偏好 (balanced/cost/time/stable)
            - tradePref: 贸易条款偏好 (auto/FOB/CIF/DDP/...)
        :return: 推荐结果字典
        """
        # 调用LLM客户端（内含规则引擎降级逻辑）
        result = self.llm_client.recommend(input_data)

        # 添加引擎元信息
        result["engine"] = "data_driven_v3"
        result["data_sources"] = [
            "各基地产能",
            "各工厂最大订单数",
            "海运费参考标准",
            "港杂费标准_贸易条款承运商箱型港口",
            "工厂到起运港拖车费",
            "运抵国与目的港",
        ]
        result["llm_enabled"] = LLM_ENABLED

        return result

    def get_countries(self):
        """获取所有支持的运抵国列表"""
        return self.kb.all_countries

    def get_country_info(self, country):
        """获取指定运抵国的详细信息"""
        info = {
            "country": country,
            "dest_ports": [p["port"] for p in self.kb.country_dest_ports.get(country, [])],
            "origin_ports": [p["port"] for p in self.kb.country_origin_ports.get(country, [])],
            "trade_terms": [{"term": t["term"], "count": t["count"]} for t in self.kb.country_trade_terms.get(country, [])],
            "ocean_days": self.kb.country_ocean_days.get(country),
            "avg_cost": getattr(self.kb, 'country_avg_cost', {}).get(country),
            "fee_breakdown": self.kb.get_fee_breakdown(country),
        }
        return info

    def get_factories(self):
        """获取所有工厂信息"""
        return self.kb.factory_info

    def get_kb_summary(self):
        """获取知识库摘要"""
        return self.kb.get_summary()
