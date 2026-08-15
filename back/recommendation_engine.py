"""
推荐引擎 — 整合知识库、费用计算器、LLM客户端的统一推荐入口
"""
from llm_client import LLMClient
from knowledge_base import KnowledgeBase
from cost_calculator import CostCalculator
import config
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
        self._retriever = None
        self._executor = None
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
        # 自适应 Agentic RAG 编排（含查询路由/检索增强/反思校验）
        if config.RAG_ENABLED and config.AGENT_ENABLED:
            result = self.executor.run(input_data=input_data)
            result.setdefault("engine", "adaptive_agentic_rag")
        else:
            # 原有流程：规则引擎 + 单次 LLM（降级兼容）
            result = self.llm_client.recommend(input_data)
            result.setdefault("engine", "data_driven_v3")

        # 添加引擎元信息
        result.setdefault("data_sources", [
            "工厂分配区间规则",
            "海运费参考标准",
            "港杂费标准_贸易条款承运商箱型港口",
            "工厂到起运港拖车费",
            "运抵国与目的港",
        ])
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

    # ===== 自适应 Agentic RAG =====
    @property
    def retriever(self):
        """混合检索器（惰性构建）"""
        if self._retriever is None:
            from retriever import get_retriever
            self._retriever = get_retriever()
        return self._retriever

    @property
    def executor(self):
        """Agent 执行器（惰性构建，复用引擎的 LLM 客户端）"""
        if self._executor is None:
            from agent.executor import get_executor
            self._executor = get_executor(llm_client=self.llm_client)
        return self._executor

    def search_kb(self, query, top_k=8):
        """知识检索接口（供 /api/kb/search 与调试使用）"""
        results = self.retriever.retrieve(query=query, top_k=top_k)
        return {"query": query, "count": len(results), "results": results}

    def kb_stats(self):
        """检索库统计（供 /api/kb/stats）"""
        return self.retriever.store.stats()

    def rebuild_kb(self):
        """强制重建检索索引（供 /api/kb/rebuild）"""
        self.retriever.store.build(force=True)
        return self.kb_stats()

    def chat(self, message, input_data=None, session_id=None):
        """对话式推荐/问答（供 /api/chat 使用）"""
        return self.executor.run(
            input_data=input_data or {},
            message=message,
            session_id=session_id,
        )
