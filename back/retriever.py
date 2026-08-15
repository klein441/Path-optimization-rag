"""
混合检索器 — 自适应 Agentic RAG 的检索层

把三类检索融合为一份带引用的上下文：
1. 结构化检索：直接查询 KnowledgeBase（工厂/港口/条款/海运天数等，精确权威）
2. 关键词检索：RagStore 的 BM25 风格命中
3. 向量检索：RagStore 的语义（或哈希回退）相似度

同时按查询画像（profile）自适应调整 top_k、检索源、是否查询扩展。
"""
import re

import config
from knowledge_base import KnowledgeBase
from rag_store import get_rag_store

# ===== 查询扩展同义词 =====
_SYNONYMS = {
    "丁腈": ["丁腈手套", "手套", "nitrile"],
    "pvc": ["pvc手套", "手套", "聚氯乙烯"],
    "pe": ["pe产品", "pe手套", "聚乙烯"],
    "美国": ["北美", "usa", "美国西海岸", "美国东海岸"],
    "德国": ["欧洲", "汉堡"],
    "船期": ["船期", "etd", "截关", "开船"],
    "到货": ["到货时间", "eta", "交期", "arrival"],
    "加急": ["赶船期", "加急", "urgent", "快"],
}

_DEFAULT_PROFILE = {
    "top_k": 8,
    "sources": ["structured", "keyword", "vector"],
    "multi_round": False,
    "query_expansion": False,
    "use_rerank": False,
}


class Retriever:
    """混合检索器（单例）"""

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
        self.store = get_rag_store()
        self._initialized = True

    # ===== 对外接口 =====
    def retrieve(self, query="", input_data=None, profile=None, top_k=None):
        """混合检索

        :param query: 自然语言查询/描述
        :param input_data: 结构化表单（可空）
        :param profile: 检索画像 dict（覆盖默认）
        :param top_k: 返回条数（覆盖 profile.top_k）
        :return: [dict] 每条含 text/source/chunk_type/score/metadata/structured
        """
        p = dict(_DEFAULT_PROFILE)
        if profile:
            p.update(profile)
        k = int(top_k or p.get("top_k") or config.RETRIEVAL_TOP_K)
        k = max(1, min(k, config.RETRIEVAL_MAX_K))

        sources = p.get("sources") or ["structured", "keyword", "vector"]
        results = []

        # 1) 结构化检索
        if "structured" in sources:
            structured = self._structured_knowledge(input_data or {}, query)
            for s in structured:
                s["structured"] = True
                s["score"] = 1.0
            results.extend(structured)

        # 2) 语义/关键词检索
        if "keyword" in sources or "vector" in sources:
            expanded = self._expand_query(query)
            exact_terms = self._exact_terms(query, input_data or {})
            store_k = max(1, k * 2 - len(results))
            hits = self.store.search(expanded, top_k=store_k,
                                     exact_terms=exact_terms if "keyword" in sources else None)
            for h in hits:
                results.append({
                    "chunk_id": h.chunk_id,
                    "text": h.text,
                    "source": h.source,
                    "chunk_type": h.chunk_type,
                    "score": float(h.score),
                    "metadata": h.metadata or {},
                    "structured": False,
                })

        # 3) 融合排序：结构化在前（权威），其余按分数
        structured_items = [r for r in results if r["structured"]]
        semantic_items = sorted([r for r in results if not r["structured"]],
                                key=lambda x: x["score"], reverse=True)
        # 去重（结构化优先）
        seen = set()
        merged = []
        for r in structured_items + semantic_items:
            key = (r.get("chunk_id") or r["text"][:40])
            if key in seen:
                continue
            seen.add(key)
            merged.append(r)

        # 4) 可选重排（占位：当前用分数融合代替，后续可接 bge-reranker）
        if p.get("use_rerank"):
            merged = self._rerank(query, merged)

        return merged[:k]

    def retrieve_text(self, query="", input_data=None, profile=None, top_k=None, max_chars=6000):
        """检索并拼成适合注入 Prompt 的文本块"""
        chunks = self.retrieve(query=query, input_data=input_data, profile=profile, top_k=top_k)
        parts = []
        used = 0
        for c in chunks:
            block = f"- [{c['chunk_type']} | {c['source']}] {c['text']}"
            used += len(block)
            if used > max_chars:
                break
            parts.append(block)
        return "\n".join(parts)

    # ===== 结构化知识 =====
    def _structured_knowledge(self, input_data, query):
        out = []
        country = (input_data.get("destCountry") or "").strip()
        product = (input_data.get("productType") or "").strip()
        dest_port = (input_data.get("destPort") or "").strip()

        # 从查询文本识别运抵国：纯咨询问题（无表单，如「从中国到美国海运大概要多少天」）
        # 也能命中「运抵国 美国 常用目的港/海运天数」等国家维度结构化知识。
        if not country and (query or "").strip():
            _q = query
            _cands = [c for c in self.kb.all_countries if c and c in _q]
            if _cands:
                # 「从A到B」型问句中目的地通常靠后：取最靠右的匹配，同名取更长
                country = max(_cands, key=lambda c: (_q.rindex(c), len(c)))

        # 工厂信息：仅当查询/表单涉及产品、工厂或「哪些工厂」类咨询时输出，
        # 避免无信号时 5 家工厂以 score=1.0 无条件霸占 top-k，把真正相关的报告/常量/术语挤出去。
        q_low2 = (query or "").lower()
        query_product = ""
        for _pc, _pt in (("丁腈", "丁腈手套"), ("pvc", "PVC手套"), ("pe", "PE产品")):
            if _pc in q_low2:
                query_product = _pt
                break
        eff_product = product or query_product
        mention_factory = any(name in (query or "") for name in self.kb.factory_info)
        if eff_product or mention_factory or "工厂" in (query or ""):
            for name, info in self.kb.factory_info.items():
                products = info.get("products", [])
                if eff_product and products and not any(eff_product.split(",")[0] in p for p in products):
                    continue
                out.append({
                    "chunk_id": f"struct_factory_{name}",
                    "text": (f"工厂: {name} | 简称: {info.get('short_name', '')} | 区域: {info.get('region', '')} "
                             f"| 省份: {info.get('province', '')} | 默认港: {info.get('default_port', '')} "
                             f"| 产品: {','.join(products)}"),
                    "source": "KnowledgeBase",
                    "chunk_type": "knowledge",
                    "metadata": {"factory": name},
                })

        if country:
            ports = self.kb.country_dest_ports.get(country, [])
            if ports:
                out.append({
                    "chunk_id": f"struct_dest_{country}",
                    "text": f"运抵国 {country} 常用目的港: {', '.join(p['port'] for p in ports)}",
                    "source": "KnowledgeBase", "chunk_type": "knowledge",
                    "metadata": {"country": country},
                })
            terms = self.kb.country_trade_terms.get(country, [])
            if terms:
                out.append({
                    "chunk_id": f"struct_term_{country}",
                    "text": f"运抵国 {country} 常用贸易条款: " + ", ".join(f"{t['term']}({t['count']}次)" for t in terms),
                    "source": "KnowledgeBase", "chunk_type": "knowledge",
                    "metadata": {"country": country},
                })
            days = self.kb.country_ocean_days.get(country)
            if days:
                median = days.get("median") if isinstance(days, dict) else days
                out.append({
                    "chunk_id": f"struct_days_{country}",
                    "text": f"运抵国 {country} 海运天数约 {median} 天",
                    "source": "KnowledgeBase", "chunk_type": "knowledge",
                    "metadata": {"country": country},
                })
            lines_info = self.kb.get_shipping_lines(country)
            lines = (lines_info or {}).get("lines") or []
            if lines:
                names = "、".join(f"{l.get('name', '')}({l.get('transit_days', '?')}天)" for l in lines[:3])
                out.append({
                    "chunk_id": f"struct_line_{country}",
                    "text": f"运抵国 {country} 推荐船公司: {names}",
                    "source": "KnowledgeBase", "chunk_type": "knowledge",
                    "metadata": {"country": country},
                })

        # 合约海运费：查询提到具体起运港（如「上海」「宁波」）时给出该港→目的港的合约费率；
        # 查询带价格/划算意图且未指定起运港时，给出到目的港最便宜的前3个始发港费率（如 q06）。
        if dest_port:
            _qq = (query or "")
            _mentioned = [cn for cn in config.DOMESTIC_ORIGIN_PORTS if cn and cn in _qq]
            if _mentioned:
                for _cn in _mentioned:
                    _rate = self._best_contract_rate(_cn, dest_port)
                    if _rate:
                        out.append({
                            "chunk_id": f"struct_rate_{_cn}",
                            "text": (f"合约海运费 {_cn}→{dest_port}: {_rate['carrier']} "
                                     f"USD {_rate['rate_usd']}/40HC（约 CNY{_rate['rate_cny']}）"),
                            "source": "KnowledgeBase", "chunk_type": "knowledge",
                            "metadata": {"origin_port": _cn, "dest_port": dest_port},
                        })
            elif any(_k in _qq for _k in ("海运费", "划算", "便宜", "价格", "费用", "多少钱", "报价")):
                for _cn, _rate in self._top_origin_rates(dest_port, limit=3):
                    out.append({
                        "chunk_id": f"struct_rate_{_cn}",
                        "text": (f"合约海运费 {_cn}→{dest_port}: {_rate['carrier']} "
                                 f"USD {_rate['rate_usd']}/40HC（约 CNY{_rate['rate_cny']}）"),
                        "source": "KnowledgeBase", "chunk_type": "knowledge",
                        "metadata": {"origin_port": _cn, "dest_port": dest_port},
                    })

        # 贸易条款术语：查询中明确提到条款名（FOB/DDP/CIF…）时，把术语定义作为结构化权威知识输出，
        # 保证术语类咨询（如「FOB和DDP有什么区别」）能检索到 kb.trade_terms 的定义，而不是只靠报告兜底。
        q_low = (query or "").lower()
        mentioned = [t for t in self.kb.trade_terms if t.lower() in q_low]
        if "贸易条款" in q_low or "贸易术语" in q_low:
            mentioned = list(self.kb.trade_terms.keys())
        for t in mentioned:
            info = self.kb.trade_terms.get(t) or {}
            out.append({
                "chunk_id": f"struct_term_{t}",
                "text": (f"贸易条款 {t} ({info.get('full', '')}): {info.get('desc', '')} "
                         f"| 卖方责任: {info.get('seller_resp', '')} | 费用范围: {info.get('cost_scope', '')}"),
                "source": "KnowledgeBase", "chunk_type": "knowledge",
                "metadata": {"term": t},
            })
        return out

    # ===== 查询扩展 =====
    def _expand_query(self, query):
        q = query or ""
        if config.QUERY_EXPANSION_ENABLED:
            low = q.lower()
            for key, syns in _SYNONYMS.items():
                if key in low or key.upper() in q:
                    q = q + " " + " ".join(syns)
        return q.strip()

    def _exact_terms(self, query, input_data):
        terms = []
        country = (input_data.get("destCountry") or "").strip()
        product = (input_data.get("productType") or "").strip()
        dest_port = (input_data.get("destPort") or "").strip()
        if country:
            terms.append(country)
        if product:
            terms.append(product.split(",")[0])
        if dest_port:
            terms.append(dest_port)
        for t in re.findall(r"[A-Za-z]{2,}", query or ""):
            terms.append(t)
        # 知识库中的工厂/港口专名
        for fname in list(self.kb.factory_info.keys())[:10]:
            if fname in (query or ""):
                terms.append(fname)
        return [t for t in terms if t]

    def _contract_df(self):
        """合约海运费表（模块级缓存来自 llm_client，懒加载避免循环依赖）"""
        try:
            from llm_client import _load_contract_df
        except Exception:
            return None
        try:
            return _load_contract_df()
        except Exception:
            return None

    def _best_contract_rate(self, origin_cn, dest_port, box_type="40HQ"):
        """《海运费参考标准》中 起运港→目的港 的最低有效合约费率（默认 40HQ 走 40HC 报价列）"""
        try:
            import pandas as pd
            from llm_client import _contract_port_match
        except Exception:
            return None
        df = self._contract_df()
        if df is None or df.empty or "起运港" not in df.columns or "目的港" not in df.columns:
            return None
        box_col = "40HC报价"
        if box_col not in df.columns:
            return None
        today = pd.Timestamp.now().normalize()
        try:
            origin_mask = df["起运港"].apply(lambda x: _contract_port_match(x, origin_cn))
            dest_mask = df["目的港"].apply(lambda x: _contract_port_match(x, dest_port))
            matched = df[origin_mask & dest_mask & df[box_col].notna() & (df[box_col] > 0)]
        except Exception:
            return None
        if matched.empty:
            return None
        rows = []
        for _, row in matched.iterrows():
            try:
                rate = float(row[box_col])
            except (TypeError, ValueError):
                continue
            is_valid = True
            frm, to = row.get("合约生效日期"), row.get("合约失效日期")
            if pd.notna(frm) and today < frm:
                is_valid = False
            if pd.notna(to) and today > to:
                is_valid = False
            rows.append((rate, is_valid, str(row.get("船公司简称", "") or "").strip()))
        if not rows:
            return None
        valid = [r for r in rows if r[1]]
        best = min(valid, key=lambda r: r[0]) if valid else min(rows, key=lambda r: r[0])
        rate_usd, is_valid, carrier = best
        return {
            "carrier": carrier or "合约",
            "rate_usd": rate_usd,
            "rate_cny": round(rate_usd * config.USD_TO_CNY, 2),
            "is_valid": is_valid,
        }

    def _top_origin_rates(self, dest_port, limit=3):
        """到目的港海运费最便宜的前 N 个始发港费率（有效合约优先）"""
        out = []
        for _cn in config.DOMESTIC_ORIGIN_PORTS:
            _rate = self._best_contract_rate(_cn, dest_port)
            if _rate:
                out.append((_cn, _rate))
        out.sort(key=lambda x: (0 if x[1]["is_valid"] else 1, x[1]["rate_cny"]))
        return out[:limit]

    def _rerank(self, query, items):
        """占位重排：按 chunk_type 优先级 + 分数加权（后续可接 bge-reranker）"""
        priority = {"rule": 1.0, "mapping": 1.0, "knowledge": 0.9, "quote": 0.8,
                    "fee": 0.8, "land_freight": 0.8, "transit_time": 0.8, "constant": 0.7, "history": 0.7,
                    "report": 0.75}
        for it in items:
            it["score"] = it.get("score", 0) * priority.get(it.get("chunk_type"), 0.7)
        return sorted(items, key=lambda x: (x["structured"], x["score"]), reverse=True)


def get_retriever():
    return Retriever()