"""
LLM客户端 — 基于真实数据构建富Prompt，调用LLM生成推荐方案
当无API Key时自动降级为规则引擎
"""
import json
import requests
from datetime import datetime, timedelta
from config import LLM_API_URL, LLM_API_KEY, LLM_MODEL, LLM_TIMEOUT, LLM_ENABLED, NORTH_AMERICA, FDA_COUNTRIES
from knowledge_base import KnowledgeBase
from cost_calculator import CostCalculator


class LLMClient:
    """LLM推荐客户端"""

    def __init__(self):
        self.kb = KnowledgeBase()
        self.kb.build()
        self.cost_calc = CostCalculator()

    def recommend(self, input_data):
        """
        生成推荐方案
        :param input_data: 用户输入
        :return: 推荐结果字典
        """
        # Step 1: 规则引擎预处理 — 确定候选方案
        candidates = self._generate_candidates(input_data)

        # Step 2: 调用LLM优化推荐（如有API Key）
        if LLM_ENABLED:
            try:
                result = self._call_llm(input_data, candidates)
                if result:
                    result["source"] = "llm"
                    return result
            except Exception as e:
                print(f"[LLM] 调用失败，降级为规则引擎: {e}")

        # Step 3: 规则引擎生成最终推荐
        result = self._rule_based_recommend(input_data, candidates)
        result["source"] = "rule_engine"
        return result

    def _generate_candidates(self, input_data):
        """生成候选方案列表"""
        product_type = input_data.get("productType", "")
        dest_country = input_data.get("destCountry", "")
        transport_pref = input_data.get("transportPref", "balanced")

        # 1. 查找符合条件的工厂
        factories = self._find_factories(product_type, dest_country)

        # 2. 为每个工厂生成方案
        candidates = []
        for factory in factories:
            factory_name = factory["name"]
            info = factory["info"]

            # 确定始发港
            origin_port = self.kb.get_best_origin_port(dest_country, factory_name)
            # 确定目的港
            dest_port = self.kb.get_best_dest_port(dest_country) or dest_country + "主港"
            # 确定贸易条款
            trade_term = self.kb.get_best_trade_term(dest_country)
            # 确定箱型
            volume = float(input_data.get("volume", 0) or 0)
            weight = float(input_data.get("weight", 0) or 0)
            box_type = self.cost_calc.suggest_box_type(volume, weight)

            # 计算费用
            cost = self.cost_calc.calculate(input_data, factory_name, origin_port, dest_port, trade_term, box_type)

            # 计算时间线
            timeline = self._calculate_timeline(input_data, factory_name, dest_country)

            # 计算优先级分数
            score = self._calculate_score(info, cost, timeline, transport_pref, dest_country)

            # 获取承运商推荐
            carrier_rec = self.kb.get_carrier_recommendation(factory_name)

            # 获取船公司推荐
            shipping_line = self.kb.get_best_shipping_line(dest_country)
            shipping_lines_info = self.kb.get_shipping_lines(dest_country)

            candidates.append({
                "factory": factory_name,
                "factory_short": info["short_name"],
                "region": info["region"],
                "origin_port": origin_port,
                "dest_port": dest_port,
                "trade_term": trade_term,
                "box_type": box_type,
                "cost": cost,
                "timeline": timeline,
                "score": score,
                "carrier": carrier_rec,
                "shipping_line": shipping_line,
                "shipping_lines": shipping_lines_info,
                "factory_info": {
                    "pvc_capacity": info["pvc_capacity"],
                    "nitrile_capacity": info["nitrile_capacity"],
                    "pvc_share": info["pvc_share"],
                    "nitrile_share": info["nitrile_share"],
                    "region": info["region"],
                    "province": info["province"],
                },
            })

        # 按分数排序
        candidates.sort(key=lambda x: x["score"], reverse=True)
        return candidates

    def _find_factories(self, product_type, dest_country):
        """查找符合条件的工厂"""
        # 从知识库获取能生产该产品的工厂
        factories = self.kb.get_factory_by_product(product_type)

        if not factories:
            # 如果没有精确匹配，使用全部工厂
            for name, info in self.kb.factory_info.items():
                factories.append({"name": name, "info": info})

        # 北美市场优先海外工厂
        is_north_america = dest_country in NORTH_AMERICA
        if is_north_america:
            factories.sort(key=lambda x: 0 if x["info"]["region"] == "海外" else 1)

        return factories

    def _calculate_timeline(self, input_data, factory_name, dest_country):
        """计算运输时间线"""
        cargo_ready_str = input_data.get("cargoReady", "")
        ship_schedule_str = input_data.get("shipSchedule", "")

        try:
            cargo_ready = datetime.fromisoformat(cargo_ready_str.replace("Z", "")) if cargo_ready_str else datetime.now()
        except:
            cargo_ready = datetime.now()

        try:
            ship_schedule = datetime.fromisoformat(ship_schedule_str.replace("Z", "")) if ship_schedule_str else cargo_ready + timedelta(days=7)
        except:
            ship_schedule = cargo_ready + timedelta(days=7)

        # 内陆运输天数（工厂到港口）
        info = self.kb.factory_info.get(factory_name, {})
        region = info.get("region", "国内")
        if region == "海外":
            inland_days = 2
        else:
            province = info.get("province", "")
            if province in ["山东"]:
                inland_days = 2
            elif province in ["安徽", "江西"]:
                inland_days = 3
            elif province in ["上海", "江苏"]:
                inland_days = 1
            else:
                inland_days = 3

        # 海运天数
        ocean_days = int(self.kb.get_ocean_days(dest_country))
        if ocean_days <= 0:
            ocean_days = 30

        # ETD = max(货好时间 + 内陆运输天数, 期望船期)
        earliest_etd = cargo_ready + timedelta(days=inland_days)
        etd = max(earliest_etd, ship_schedule)

        # ETA = ETD + 海运天数
        eta = etd + timedelta(days=ocean_days)

        return {
            "cargo_ready": cargo_ready.strftime("%Y-%m-%d"),
            "ship_schedule": ship_schedule.strftime("%Y-%m-%d"),
            "inland_days": inland_days,
            "ocean_days": ocean_days,
            "etd": etd.strftime("%Y-%m-%d"),
            "eta": eta.strftime("%Y-%m-%d"),
            "total_days": (eta - cargo_ready).days,
        }

    def _calculate_score(self, info, cost, timeline, transport_pref, dest_country):
        """计算方案优先级分数（0-100）"""
        score = 50.0

        # 产能加分
        total_cap = info.get("total_capacity", 0)
        if total_cap > 1000000:
            score += 15
        elif total_cap > 500000:
            score += 10
        elif total_cap > 100000:
            score += 5

        # 区域策略加分
        region = info.get("region", "国内")
        if dest_country in NORTH_AMERICA and region == "海外":
            score += 15
        elif dest_country not in NORTH_AMERICA and region == "国内":
            score += 10

        # 费用影响
        total_cost = cost["total_cny"]
        if total_cost < 5000:
            score += 10
        elif total_cost < 8000:
            score += 5
        elif total_cost > 15000:
            score -= 5

        # 时效影响
        total_days = timeline["total_days"]
        if total_days < 25:
            score += 10
        elif total_days < 40:
            score += 5
        elif total_days > 50:
            score -= 5

        # 运输偏好调整
        if transport_pref == "cost":
            score -= total_cost * 0.001
        elif transport_pref == "time":
            score -= total_days * 0.3

        return round(max(0, min(100, score)), 1)

    def _rule_based_recommend(self, input_data, candidates):
        """规则引擎生成推荐"""
        if not candidates:
            return {"error": "未找到符合条件的工厂"}

        primary = candidates[0]
        alternatives = candidates[1:4]

        reasoning = self._generate_reasoning(input_data, primary, alternatives)

        return {
            "input": input_data,
            "primary": {
                "factory": primary["factory"],
                "factory_short": primary["factory_short"],
                "region": primary["region"],
                "departurePort": primary["origin_port"],
                "destPort": primary["dest_port"],
                "tradeTerm": primary["trade_term"],
                "tradeTermInfo": self.kb.trade_terms.get(primary["trade_term"], {}),
                "boxType": primary["box_type"],
                "cost": primary["cost"],
                "timeline": primary["timeline"],
                "factoryInfo": primary["factory_info"],
                "carrier": primary.get("carrier", {}),
                "shippingLine": primary.get("shipping_line", {}),
                "shippingLines": primary.get("shipping_lines", {}),
                "score": primary["score"],
                "needFDA": input_data.get("destCountry") in FDA_COUNTRIES,
            },
            "alternatives": [
                {
                    "factory": a["factory"],
                    "factory_short": a["factory_short"],
                    "region": a["region"],
                    "departurePort": a["origin_port"],
                    "destPort": a["dest_port"],
                    "tradeTerm": a["trade_term"],
                    "boxType": a["box_type"],
                    "cost": a["cost"],
                    "timeline": a["timeline"],
                    "carrier": a.get("carrier", {}),
                    "shippingLine": a.get("shipping_line", {}),
                    "score": a["score"],
                }
                for a in alternatives
            ],
            "reasoning": reasoning,
            "dataStats": self._get_data_stats(input_data.get("destCountry", "")),
            "eligibleFactories": len(candidates),
            "generatedAt": datetime.now().isoformat(),
        }

    def _generate_reasoning(self, input_data, primary, alternatives):
        """生成推荐理由"""
        product = input_data.get("productType", "")
        country = input_data.get("destCountry", "")
        factory = primary["factory_short"]
        origin = primary["origin_port"]
        dest = primary["dest_port"]
        term = primary["trade_term"]
        cost = primary["cost"]["total_cny"]
        days = primary["timeline"]["total_days"]

        reasons = []

        # 工厂选择理由
        cap_share = 0
        if product == "丁腈手套":
            cap_share = primary["factory_info"].get("nitrile_share", 0)
        elif product == "PVC手套":
            cap_share = primary["factory_info"].get("pvc_share", 0)

        if cap_share > 20:
            reasons.append(f"{factory}是{product}的主要生产基地，产能占比{cap_share}%，供应充足")
        else:
            reasons.append(f"{factory}具备{product}生产能力，可满足本次出货需求")

        # 港口选择理由
        port_count = len(self.kb.country_origin_ports.get(country, []))
        if port_count > 0:
            reasons.append(f"从{origin}发货至{dest}，该路线历史出货{self.kb.country_origin_ports[country][0]['count']}次，航线成熟稳定")

        # 贸易条款理由
        term_stats = self.kb.country_trade_terms.get(country, [])
        if term_stats:
            reasons.append(f"{country}市场历史最常用贸易条款为{term}（使用{term_stats[0]['count']}次）")

        # 北美市场特殊策略
        if country in NORTH_AMERICA:
            if primary["region"] == "海外":
                reasons.append(f"北美市场优先从海外基地发货，可节省海运时效和成本")
            else:
                reasons.append(f"国内基地至北美路线成熟，运力充足")

        # 费用理由
        fee_count = len(primary["cost"]["items"])
        reasons.append(f"费用方案含{fee_count}项明细，总费用约{cost:.0f} CNY（{cost/7.2:.0f} USD）")

        # 时效理由
        reasons.append(f"预计总运输周期{days}天（内陆{primary['timeline']['inland_days']}天+海运{primary['timeline']['ocean_days']}天）")

        # 承运商（车队）推荐理由
        carrier = primary.get("carrier", {})
        if carrier.get("recommended"):
            carrier_type = carrier.get("type", "外包")
            self_ratio = carrier.get("self_owned_ratio", 0)
            carrier_count = carrier.get("count", 0)
            if carrier_type == "自有":
                reasons.append(f"推荐使用工厂自有车队运输（历史使用{carrier_count}次，自有占比{self_ratio}%），成本可控")
            else:
                reasons.append(f"推荐承运商{carrier['recommended']}（{carrier_type}，历史{carrier_count}次），该工厂自有车队占比{self_ratio}%")

        # 船公司推荐理由
        shipping = primary.get("shipping_line", {})
        if shipping.get("name"):
            reasons.append(f"推荐船公司{shipping['name']}（{shipping.get('frequency', '')}，{shipping.get('transit_days', '?')}天到港，{shipping.get('advantage', '')}）")

        # 备选方案
        if alternatives:
            alt_names = "、".join(a["factory_short"] for a in alternatives[:2])
            reasons.append(f"备选方案：{alt_names}可根据实际产能和船期灵活调整")

        return "。".join(reasons) + "。"

    def _get_data_stats(self, country):
        """获取该运抵国的历史数据统计"""
        stats = {}
        # 历史出货次数
        origin_ports = self.kb.country_origin_ports.get(country, [])
        stats["total_shipments"] = sum(p["count"] for p in origin_ports)
        # 常用港口
        stats["common_origin_ports"] = [p["port"] for p in origin_ports[:3]]
        dest_ports = self.kb.country_dest_ports.get(country, [])
        stats["common_dest_ports"] = [p["port"] for p in dest_ports[:3]]
        # 常用贸易条款
        terms = self.kb.country_trade_terms.get(country, [])
        stats["common_trade_terms"] = [{"term": t["term"], "count": t["count"]} for t in terms[:3]]
        # 海运天数
        ocean_days = self.kb.country_ocean_days.get(country)
        if ocean_days:
            stats["ocean_days"] = ocean_days
        # 平均费用
        avg_cost = self.kb.country_avg_cost.get(country)
        if avg_cost:
            stats["avg_cost"] = avg_cost
        # 费用明细
        fee_breakdown = self.kb.get_fee_breakdown(country)
        if fee_breakdown:
            stats["fee_breakdown"] = {k: v["median"] for k, v in fee_breakdown.items()}

        return stats

    def _build_prompt(self, input_data, candidates):
        """构建LLM Prompt（含真实数据上下文）"""
        product = input_data.get("productType", "")
        country = input_data.get("destCountry", "")
        box_count = input_data.get("boxCount", "")
        weight = input_data.get("weight", "")
        volume = input_data.get("volume", "")

        # 知识库摘要
        kb_summary = self.kb.get_summary()

        # 候选方案信息
        candidate_info = []
        for i, c in enumerate(candidates[:5]):
            carrier = c.get('carrier', {})
            shipping = c.get('shipping_line', {})
            candidate_info.append(f"""
方案{i+1}：
  工厂：{c['factory']}（{c['factory_short']}，{c['region']}）
  始发港→目的港：{c['origin_port']} → {c['dest_port']}
  贸易条款：{c['trade_term']}
  箱型：{c['box_type']}
  总费用：{c['cost']['total_cny']} CNY / {c['cost']['total_usd']} USD
  费用明细：{json.dumps([{k: v for k, v in item.items() if k in ('name', 'amount_cny')} for item in c['cost']['items']], ensure_ascii=False)}
  运输周期：{c['timeline']['total_days']}天（内陆{c['timeline']['inland_days']}天+海运{c['timeline']['ocean_days']}天）
  ETD：{c['timeline']['etd']}，ETA：{c['timeline']['eta']}
  产能占比：PVC {c['factory_info']['pvc_share']}%，丁腈 {c['factory_info']['nitrile_share']}%
  承运商（车队）：{carrier.get('recommended', '未知')}（{carrier.get('type', '外包')}，历史{carrier.get('count', 0)}次，自有比例{carrier.get('self_owned_ratio', 0)}%）
  船公司：{shipping.get('name', '未知')}（{shipping.get('code', '')}，{shipping.get('transit_days', '?')}天，{shipping.get('frequency', '')}）
  综合评分：{c['score']}/100
""")

        # 历史数据统计
        data_stats = self._get_data_stats(country)

        prompt = f"""你是一位物流运输路径优化专家。请基于以下真实历史数据和候选方案，为用户推荐最优物流方案。

## 用户需求
- 产品类型：{product}
- 运抵国：{country}
- 箱数：{box_count}
- 重量：{weight} kg
- 体积：{volume} CBM
- 货好时间：{input_data.get('cargoReady', '')}
- 期望船期：{input_data.get('shipSchedule', '')}

## 知识库摘要
- 工厂数量：{kb_summary['total_factories']}个
- 覆盖运抵国：{kb_summary['total_countries']}个
- 始发港数量：{kb_summary['total_origin_ports']}个
- TMS费用类型：{kb_summary['total_fee_categories']}个大类
- 海运费中位数：{kb_summary['avg_shipping_fee']} CNY
- 货好到离港平均天数：{kb_summary['avg_cr_to_etd_days']}天

## 该运抵国历史数据统计
- 历史出货次数：{data_stats.get('total_shipments', 0)}次
- 常用始发港：{data_stats.get('common_origin_ports', [])}
- 常用目的港：{data_stats.get('common_dest_ports', [])}
- 常用贸易条款：{data_stats.get('common_trade_terms', [])}
- 海运天数：{data_stats.get('ocean_days', {})}
- 平均总费用：{data_stats.get('avg_cost', {})}
- 费用明细中位数：{data_stats.get('fee_breakdown', {})}

## 候选方案
{''.join(candidate_info)}

## 请输出JSON格式的推荐结果
请从候选方案中选择最优方案，并给出详细推荐理由。输出格式：
{{
  "primary_index": 0,
  "reasoning": "推荐理由（200字以内）",
  "risk_warning": "风险提示（如有）",
  "optimization_suggestion": "优化建议（如有）"
}}

请综合考虑：产能匹配度、运输成本、时效性、路线成熟度、贸易条款合理性。"""

        return prompt

    def _call_llm(self, input_data, candidates):
        """调用LLM API"""
        prompt = self._build_prompt(input_data, candidates)

        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {LLM_API_KEY}",
        }
        payload = {
            "model": LLM_MODEL,
            "messages": [
                {"role": "system", "content": "你是物流运输路径优化专家，擅长基于数据分析给出最优物流方案。"},
                {"role": "user", "content": prompt},
            ],
            "temperature": 0.3,
            "max_tokens": 2000,
        }

        resp = requests.post(LLM_API_URL, json=payload, headers=headers, timeout=LLM_TIMEOUT)
        resp.raise_for_status()
        data = resp.json()
        content = data["choices"][0]["message"]["content"]

        # 解析LLM返回的JSON
        try:
            llm_result = json.loads(content)
        except:
            import re
            match = re.search(r'\{.*\}', content, re.DOTALL)
            if match:
                llm_result = json.loads(match.group())
            else:
                return None

        # 将LLM选择映射到候选方案
        primary_idx = llm_result.get("primary_index", 0)
        if primary_idx >= len(candidates):
            primary_idx = 0

        result = self._rule_based_recommend(input_data, candidates)
        # 用LLM选择的方案替换
        if primary_idx > 0:
            selected = candidates[primary_idx]
            result["primary"]["factory"] = selected["factory"]
            result["primary"]["factory_short"] = selected["factory_short"]
            result["primary"]["region"] = selected["region"]
            result["primary"]["departurePort"] = selected["origin_port"]
            result["primary"]["destPort"] = selected["dest_port"]
            result["primary"]["tradeTerm"] = selected["trade_term"]
            result["primary"]["boxType"] = selected["box_type"]
            result["primary"]["cost"] = selected["cost"]
            result["primary"]["timeline"] = selected["timeline"]
            result["primary"]["score"] = selected["score"]
            result["primary"]["carrier"] = selected.get("carrier", {})
            result["primary"]["shippingLine"] = selected.get("shipping_line", {})
            result["primary"]["shippingLines"] = selected.get("shipping_lines", {})

        # 添加LLM生成的理由
        result["reasoning"] = llm_result.get("reasoning", result["reasoning"])
        result["risk_warning"] = llm_result.get("risk_warning", "")
        result["optimization_suggestion"] = llm_result.get("optimization_suggestion", "")
        result["llm_model"] = LLM_MODEL

        return result
