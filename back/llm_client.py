"""
LLM客户端 — 基于真实数据构建富Prompt，调用LLM生成推荐方案
当无API Key时自动降级为规则引擎

推荐算法（v3）：
1. 读取《各工厂最大订单数》表格，根据手套数量过滤产能足够的工厂
2. 从11个国内始发港中，按《海运费参考标准》海运费选出到终到港最便宜的5个
3. 枚举所有 工厂×始发港 路线，逐条计算全费用，按总价排序
"""
import json
import re
import os
import time
import requests
import pandas as pd
import numpy as np
from datetime import datetime, timedelta
from config import (
    LLM_API_URL, LLM_API_KEY, LLM_MODEL, LLM_TIMEOUT, LLM_ENABLED,
    NORTH_AMERICA, FDA_COUNTRIES,
    FACTORY_MAX_ORDERS_FILE, DOMESTIC_ORIGIN_PORTS, FACTORY_MAX_ORDER_NAME_MAP,
    CONTRACT_FREIGHT_FILE, CONTRACT_BOX_COLUMNS,
    CNY_TO_USD, USD_TO_CNY,
)
from knowledge_base import KnowledgeBase
from cost_calculator import CostCalculator


# ===== 合约海运费缓存 =====
_CONTRACT_DF_CACHE = None
_CONTRACT_DF_CACHE_TIME = 0
_CONTRACT_CACHE_TTL = 600  # 10分钟

# 手套数量单位 -> 千只（工厂产能单位）
GLOVE_UNIT_TO_THOUSAND_PCS = {
    "百支": 0.1,
    "八百支": 0.8,
    "支": 0.001,
    "只": 0.001,
    "千支": 1.0,
    "千只": 1.0,
    "万支": 10.0,
    "万只": 10.0,
    "双": 0.002,
}


def _load_contract_df():
    """加载合约海运费数据（模块级缓存）"""
    global _CONTRACT_DF_CACHE, _CONTRACT_DF_CACHE_TIME
    now = time.time()
    if _CONTRACT_DF_CACHE is not None and (now - _CONTRACT_DF_CACHE_TIME) < _CONTRACT_CACHE_TTL:
        return _CONTRACT_DF_CACHE
    if not os.path.exists(CONTRACT_FREIGHT_FILE):
        print(f"[合约运费] 文件不存在: {CONTRACT_FREIGHT_FILE}")
        return pd.DataFrame()
    try:
        df = pd.read_excel(CONTRACT_FREIGHT_FILE, sheet_name=0)
        # 统一箱型列名容错
        rename_map = {}
        for col in df.columns:
            col_s = str(col).strip()
            if '20' in col_s and 'GP' in col_s and '报' in col_s:
                rename_map[col] = '20GP报价'
            elif '40' in col_s and 'GP' in col_s and '报' in col_s:
                rename_map[col] = '40GP报价'
            elif '40' in col_s and ('HC' in col_s or 'HQ' in col_s) and '报' in col_s:
                rename_map[col] = '40HC报价'
            elif '45' in col_s and ('HC' in col_s or 'HQ' in col_s) and '报' in col_s:
                rename_map[col] = '45HC报价'
        if rename_map:
            df = df.rename(columns=rename_map)
        for col in ['20GP报价', '40GP报价', '40HC报价', '45HC报价']:
            if col in df.columns:
                df[col] = pd.to_numeric(df[col], errors='coerce')
        for col in ['合约生效日期', '合约失效日期']:
            if col in df.columns:
                df[col] = pd.to_datetime(df[col], errors='coerce')
        _CONTRACT_DF_CACHE = df
        _CONTRACT_DF_CACHE_TIME = now
        print(f"[合约运费] 缓存加载: {df.shape[0]} 条记录")
        return df
    except Exception as e:
        print(f"[合约运费] 加载失败: {e}")
        return pd.DataFrame()


def _contract_port_match(contract_port_str, target_port):
    """判断合约港口字符串是否匹配目标港口

    支持格式：
    - 合约: "CNSHA / 上海/SHANGHAI" 或 "CNSHA / 上海/SHANGHAI, CNNBO / 宁波/NINGBO"
    - 目标: "上海/SHANGHAI" / "上海" / "SHANGHAI" / "洛杉矶/LOS ANGELES,CA"
    """
    if not contract_port_str or pd.isna(contract_port_str):
        return False
    if not target_port:
        return False

    target = str(target_port).strip()
    target_clean = re.sub(r',\s*[A-Z]{2,3}\s*$', '', target).strip()
    target_upper = target_clean.upper()
    target_chinese = target_clean.split('/')[0].strip() if '/' in target_clean else target_clean
    target_english = target_clean.split('/')[-1].strip() if '/' in target_clean else target_clean
    target_english = re.sub(r',\s*[A-Z]{2,3}\s*$', '', target_english).strip()

    contract_ports = [p.strip() for p in str(contract_port_str).split(',') if p.strip()]
    for cp in contract_ports:
        cp_upper = cp.upper()
        if target_chinese and target_chinese in cp:
            return True
        if target_english and target_english.upper() in cp_upper:
            return True
        if target_clean and target_clean in cp:
            return True
        locode_match = re.match(r'^([A-Z]{2}[A-Z0-9]{3})\s*/', cp)
        if locode_match and target_upper and locode_match.group(1) in target_upper:
            return True
    return False


class LLMClient:
    """LLM推荐客户端"""

    def __init__(self):
        self.kb = KnowledgeBase()
        self.kb.build()
        self.cost_calc = CostCalculator()
        self._max_orders_df = None  # 延迟加载
        self._cannot_meet_arrival = False
        self._route_risk_warning = ""

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

    def _get_feasible_origin_ports(self, factory_name, dest_country):
        """
        获取工厂到指定运抵国的所有可行始发港（按历史频率排序）
        组合两个数据源：该工厂的历史始发港 + 该运抵国的历史始发港
        :return: [{"port": "青岛/QINGDAO", "count": 150, "source": "factory_history"}, ...]
        """
        seen = set()
        result = []

        # 1. 该工厂历史使用的始发港（优先，数据最直接）
        for fp in self.kb.factory_ports.get(factory_name, []):
            port = fp["port"]
            if port and port not in seen:
                result.append({"port": port, "count": fp["count"], "source": "factory_history"})
                seen.add(port)

        # 2. 该运抵国的其他始发港（工厂没用过但同一目的地用过）
        for cp in self.kb.country_origin_ports.get(dest_country, []):
            port = cp["port"]
            if port and port not in seen:
                result.append({"port": port, "count": cp["count"], "source": "country_history"})
                seen.add(port)

        # 3. 兜底：工厂配置的默认港口
        if not result:
            info = self.kb.factory_info.get(factory_name, {})
            default_port = info.get("default_port", "青岛/QINGDAO")
            if default_port and default_port not in seen:
                result.append({"port": default_port, "count": 0, "source": "default"})
                seen.add(default_port)

        return result

    def _get_feasible_dest_ports(self, dest_country):
        """
        获取运抵国的所有目的港（按历史频率排序）
        终到港是确定的（因为运抵国确定了），通常1-3个
        :return: [{"port": "洛杉矶/LOS ANGELES", "count": 200}, ...]
        """
        ports = self.kb.country_dest_ports.get(dest_country, [])
        if not ports:
            return [{"port": dest_country + "主港", "count": 0}]
        return ports

    # ===== v3 推荐算法核心 =====

    def _load_max_orders(self):
        """加载各工厂最大订单数.xlsx（延迟加载+缓存）"""
        if self._max_orders_df is not None:
            return self._max_orders_df
        if not os.path.exists(FACTORY_MAX_ORDERS_FILE):
            print(f"[工厂产能] 文件不存在: {FACTORY_MAX_ORDERS_FILE}")
            self._max_orders_df = pd.DataFrame()
            return self._max_orders_df
        try:
            df = pd.read_excel(FACTORY_MAX_ORDERS_FILE, sheet_name=0)
            # 跳过合计行（如有）
            if '公司' in df.columns:
                df = df[~df['公司'].astype(str).str.contains('合计')].copy()
            for col in ['PVC手套', '丁腈手套']:
                if col in df.columns:
                    df[col] = pd.to_numeric(df[col], errors='coerce')
            self._max_orders_df = df
            print(f"[工厂产能] 加载: {df.shape[0]} 家工厂, 列: {df.columns.tolist()}")
            return df
        except Exception as e:
            print(f"[工厂产能] 加载失败: {e}")
            self._max_orders_df = pd.DataFrame()
            return self._max_orders_df

    def _find_factories_by_capacity(self, product_type, glove_qty, glove_unit='千支'):
        """
        Step 1: 根据《各工厂最大订单数》过滤产能足够的工厂

        :param product_type: 产品类型（可能包含多个，如 "丁腈手套,PVC手套"）
        :param glove_qty: 手套数量（数值）
        :param glove_unit: 手套数量单位（千支/万支/只/双等）
        :return: [{"name": "工厂全名", "info": {...}, "capacity": float}, ...]
        """
        df = self._load_max_orders()
        if df.empty:
            print("[产能过滤] 工厂产能数据为空，回退到知识库工厂列表")
            result = []
            for name, info in self.kb.factory_info.items():
                if info.get("region") == "国内":
                    result.append({"name": name, "info": info, "capacity": 0})
            return result

        # 确定产品类型对应的产能列
        # productType 可能是 "丁腈手套" 或 "丁腈手套,PVC手套"（多选时逗号分隔）
        product_types = [p.strip() for p in product_type.split(',') if p.strip()]
        primary_product = product_types[0] if product_types else product_type

        if "PVC" in primary_product:
            capacity_col = "PVC手套"
        else:
            capacity_col = "丁腈手套"

        unit_factor = GLOVE_UNIT_TO_THOUSAND_PCS.get(str(glove_unit).strip(), 1.0)
        glove_qty_thousand = glove_qty * unit_factor
        print(f"[产能过滤] 产品={primary_product}, 数量={glove_qty}{glove_unit} -> {glove_qty_thousand}千只, 产能列={capacity_col}")

        eligible = []
        for _, row in df.iterrows():
            company = str(row['公司']).strip()
            capacity = row.get(capacity_col, 0)

            if pd.isna(capacity) or capacity <= 0:
                continue

            # 产能足够
            if glove_qty_thousand > 0 and glove_qty_thousand > capacity:
                print(f"  跳过 {company}: 产能={capacity}千只, 需求={glove_qty_thousand}千只")
                continue

            # 映射到内部工厂名
            internal_name = FACTORY_MAX_ORDER_NAME_MAP.get(company, company)
            info = self.kb.factory_info.get(internal_name)
            if info is None:
                print(f"  警告: {company} -> {internal_name} 未在知识库中找到")
                continue

            eligible.append({
                "name": internal_name,
                "info": info,
                "capacity": float(capacity),
            })
            print(f"  入选 {company} -> {internal_name}: 产能={capacity}")

        print(f"[产能过滤] 结果: {len(eligible)}/{df.shape[0]} 家工厂入选")
        return eligible

    def _find_top_5_origin_ports(self, dest_port, box_type):
        """
        Step 2: 从11个国内始发港中，按合约海运费选出到终到港最便宜的5个

        :param dest_port: 终到港（用户选择，如 "USLSA / 洛杉矶/LOS ANGELES,CA"）
        :param box_type: 箱型（如 "40HQ"）
        :return: [{"port": "青岛/QINGDAO", "rate_cny": 18000, "rate_usd": 2500, "carrier": "MSC", ...}, ...]
                 按海运费升序排列，最多5个
        """
        contract_df = _load_contract_df()
        if contract_df.empty:
            print("[海运费比价] 合约数据为空，使用前5个国内港口兜底")
            return [
                {
                    "port": std_name,
                    "port_cn": cn_name,
                    "rate_cny": 0,
                    "rate_usd": 0,
                    "carrier": "",
                    "currency": "USD",
                    "is_valid": False,
                    "note": "无合约数据",
                }
                for cn_name, std_name in list(DOMESTIC_ORIGIN_PORTS.items())[:5]
            ]

        # 确定合约箱型列名
        bt = str(box_type).strip().upper()
        if bt in ('40HC', '40HQ'):
            box_col = '40HC报价'
        elif bt in ('45HC', '45HQ'):
            box_col = '45HC报价'
        elif bt in ('20GP', '20HQ'):
            box_col = '20GP报价'
        elif bt == '40GP':
            box_col = '40GP报价'
        elif bt == '40NOR':
            box_col = '40GP报价'  # 冷代干按40GP计
        else:
            box_col = '40HC报价'

        if box_col not in contract_df.columns:
            print(f"[海运费比价] 箱型列 {box_col} 不在合约表中")
            return [
                {
                    "port": std_name,
                    "port_cn": cn_name,
                    "rate_cny": 0,
                    "rate_usd": 0,
                    "carrier": "",
                    "currency": "USD",
                    "is_valid": False,
                    "note": f"无{box_col}列",
                }
                for cn_name, std_name in list(DOMESTIC_ORIGIN_PORTS.items())[:5]
            ]

        today = pd.Timestamp.now().normalize()
        port_rates = []

        for cn_name, std_name in DOMESTIC_ORIGIN_PORTS.items():
            # 匹配起运港：中文名包含匹配
            origin_mask = contract_df['起运港'].apply(
                lambda x: _contract_port_match(x, cn_name) or _contract_port_match(x, std_name)
            )
            # 匹配目的港
            dest_mask = contract_df['目的港'].apply(
                lambda x: _contract_port_match(x, dest_port)
            )

            matched = contract_df[origin_mask & dest_mask & contract_df[box_col].notna() & (contract_df[box_col] > 0)]

            if matched.empty:
                # 宽松匹配：目的港只用中文名匹配
                dest_chinese = str(dest_port).split('/')[0].strip() if '/' in str(dest_port) else str(dest_port)
                dest_chinese = re.sub(r',\s*[A-Z]{2,3}\s*$', '', dest_chinese).strip()
                if dest_chinese and len(dest_chinese) >= 2:
                    dest_mask_loose = contract_df['目的港'].apply(lambda x: dest_chinese in str(x))
                    matched = contract_df[origin_mask & dest_mask_loose & contract_df[box_col].notna() & (contract_df[box_col] > 0)]

            if matched.empty:
                print(f"  {cn_name} -> {dest_port}: 无匹配合约")
                continue

            # 区分有效/无效合约
            valid_matched = []
            for _, row in matched.iterrows():
                rate = float(row[box_col])
                effective_from = row.get('合约生效日期')
                effective_to = row.get('合约失效日期')
                is_valid = True
                if pd.notna(effective_from) and today < effective_from:
                    is_valid = False
                if pd.notna(effective_to) and today > effective_to:
                    is_valid = False
                raw_currency = row.get('币种', 'USD')
                currency = 'USD' if pd.isna(raw_currency) else (str(raw_currency).strip().upper() or 'USD')
                valid_matched.append({
                    'rate': rate,
                    'is_valid': is_valid,
                    'carrier': str(row.get('船公司简称', '')),
                    'currency': currency,
                })

            # 有效合约中取最低价；无有效合约则取所有中最低价
            valid_rates = [m for m in valid_matched if m['is_valid']]
            best = min(valid_rates, key=lambda x: x['rate']) if valid_rates else min(valid_matched, key=lambda x: x['rate'])

            currency = best['currency']
            rate_usd = best['rate']
            rate_cny = round(rate_usd * USD_TO_CNY, 2) if currency == 'USD' else round(rate_usd, 2)

            port_rates.append({
                "port": std_name,
                "port_cn": cn_name,
                "rate_cny": rate_cny,
                "rate_usd": rate_usd,
                "carrier": best['carrier'],
                "currency": best['currency'],
                "is_valid": best['is_valid'],
                "note": f"{best['carrier']} {best['currency']} {rate_usd}/{CONTRACT_BOX_COLUMNS.get(box_type, box_col)}"
            })
            print(f"  {cn_name} -> {dest_port}: best {best['carrier']} {best['currency']} {rate_usd} "
                  f"(CNY{rate_cny}) {'[VALID]' if best['is_valid'] else '[EXPIRED]'}")

        # 按海运费升序，取前5
        port_rates.sort(key=lambda x: (0 if x['is_valid'] else 1, x['rate_cny']))
        top_5 = port_rates[:5]

        print(f"[海运费比价] 终到港={dest_port}, 箱型={box_type}, "
              f"匹配{len(port_rates)}个始发港, 取前5: {[p['port_cn'] for p in top_5]}")

        return top_5

    def _apply_modified_cost_items(self, cost, input_data):
        """重新优化：按用户在前端手动修改后的费用覆盖各候选路线的费用项，并重算总额"""
        cost_info = input_data.get("costInfo") or {}
        modified = cost_info.get("modifiedCostItems") or []
        if not modified:
            return
        mod_map = {}
        for item in modified:
            name = (item.get("name") or "").strip()
            if not name:
                continue
            try:
                amt = float(item.get("amount_cny") or 0)
            except (TypeError, ValueError):
                amt = 0.0
            mod_map[name] = amt
        if not mod_map:
            return

        items = cost.get("items") or []
        for it in items:
            it_name = it.get("name") or ""
            for mod_name, mod_amt in mod_map.items():
                # 精确匹配，或前缀匹配（如“海运费（合约价）”匹配“海运费”）
                if it_name == mod_name or it_name.startswith(mod_name):
                    it["amount_cny"] = round(mod_amt, 2)
                    if "amount_usd" in it:
                        it["amount_usd"] = round(mod_amt * CNY_TO_USD, 2)
                    it["modified_by_user"] = True
                    break
        total_cny = round(sum(i.get("amount_cny", 0) for i in items), 2)
        cost["total_cny"] = total_cny
        cost["total_usd"] = round(total_cny * CNY_TO_USD, 2)
        cost["modified_by_user"] = True

    def _generate_candidates(self, input_data):
        """
        v3 算法：生成候选方案列表

        1. 工厂过滤：读取《各工厂最大订单数》，按手套数量过滤产能足够的工厂
        2. 始发港选择：从11个国内始发港中，按合约海运费选出到终到港最便宜的5个
        3. 路线枚举：所有 工厂 × 始发港 组合，逐条计算全费用（陆运+港杂+海运+报关等）
        4. 按总费用排序返回
        """
        product_type = input_data.get("productType", "")
        dest_country = input_data.get("destCountry", "")
        dest_port = input_data.get("destPort", "")
        glove_qty = float(input_data.get("gloveQty", 0) or 0)
        glove_unit = input_data.get("gloveUnit", "千支") or "千支"
        transport_pref = input_data.get("transportPref", "balanced")

        # 箱型
        volume = float(input_data.get("volume", 0) or 0)
        weight = float(input_data.get("weight", 0) or 0)
        box_type_counts = input_data.get("boxTypeCounts", None)
        if box_type_counts and isinstance(box_type_counts, dict) and len(box_type_counts) > 0:
            box_type = list(box_type_counts.keys())[0]
        else:
            # 未指定箱型时默认 40HQ（suggest_box_type 对极小体积会返回 LCL，不适合此场景）
            suggested = self.cost_calc.suggest_box_type(volume, weight)
            box_type = suggested if suggested != 'LCL' else '40HQ'
            box_type_counts = None

        # 贸易条款
        trade_pref = input_data.get('tradePref', 'auto')
        user_trade_term = trade_pref if trade_pref and trade_pref not in ('auto', '智能推荐', '') else None
        trade_term = user_trade_term or self.kb.get_best_trade_term(dest_country)

        # ===== Step 1: 过滤产能足够的工厂 =====
        factories = self._find_factories_by_capacity(product_type, glove_qty, glove_unit)
        if not factories:
            print("[候选生成] 无产能足够的工厂！")
            return []

        # ===== Step 2: 选出海运费最便宜的前5个始发港 =====
        top_5_ports = self._find_top_5_origin_ports(dest_port, box_type)
        if not top_5_ports:
            print("[候选生成] 无匹配的始发港！")
            return []

        # ===== Step 3: 枚举所有 工厂 × 始发港 路线 =====
        candidates = []
        seen_routes = set()

        for factory in factories:
            factory_name = factory["name"]
            info = factory["info"]

            for port_info in top_5_ports:
                origin_port = port_info["port"]
                origin_port_cn = port_info.get("port_cn", origin_port)

                # 去重
                route_key = (factory_name, origin_port)
                if route_key in seen_routes:
                    continue
                seen_routes.add(route_key)

                # 计算费用（规则引擎 + 合约海运费）
                cost = self.cost_calc.calculate(
                    input_data, factory_name, origin_port, dest_port, trade_term,
                    box_type,
                    box_type_counts=box_type_counts if box_type_counts and len(box_type_counts) > 1 else None,
                    contract_ocean_rate=port_info.get("rate_cny", 0),
                    contract_ocean_info=port_info,
                )

                pricing_source = "contract" if port_info.get("rate_cny", 0) > 0 else "rule_engine"
                cost["pricing_source"] = pricing_source

                # 重新优化：按用户手动修改后的费用覆盖并重算总额（使修改后的费用参与路线排序与评分）
                self._apply_modified_cost_items(cost, input_data)

                # 计算时间线
                timeline = self._calculate_timeline(input_data, factory_name, dest_country, origin_port)

                # 计算优先级分数（基于总费用）
                score = self._calculate_score_v3(info, cost, timeline, transport_pref, port_info)

                # 承运商推荐
                carrier_rec = self.kb.get_carrier_recommendation(factory_name)

                # 船公司推荐（优先使用合约中的船公司）
                contract_carrier = port_info.get("carrier", "")
                shipping_line = self.kb.get_best_shipping_line(dest_country)
                shipping_lines_info = self.kb.get_shipping_lines(dest_country)
                if contract_carrier:
                    shipping_line = {"name": contract_carrier, "code": contract_carrier,
                                     "transit_days": shipping_line.get("transit_days", "?") if shipping_line else "?",
                                     "advantage": f"合约报价最低 ({port_info.get('note', '')})"}

                candidates.append({
                    "factory": factory_name,
                    "factory_short": info["short_name"],
                    "region": info["region"],
                    "origin_port": origin_port,
                    "origin_port_cn": origin_port_cn,
                    "origin_port_source": "contract_freight_top5",
                    "origin_port_history_count": 0,
                    "dest_port": dest_port,
                    "trade_term": trade_term,
                    "box_type": box_type,
                    "cost": cost,
                    "timeline": timeline,
                    "score": score,
                    "pricing_source": pricing_source,
                    "data_quality": cost.get("overall_quality", "medium"),
                    "carrier": carrier_rec,
                    "shipping_line": shipping_line,
                    "shipping_lines": shipping_lines_info,
                    "ocean_freight_info": port_info,  # 合约海运费明细
                    "factory_info": {
                        "pvc_capacity": info["pvc_capacity"],
                        "nitrile_capacity": info["nitrile_capacity"],
                        "pvc_share": info["pvc_share"],
                        "nitrile_share": info["nitrile_share"],
                        "region": info["region"],
                        "province": info["province"],
                    },
                })

        # ===== Step 4: 归一化评分并按到货约束排序 =====
        required_arrival = None
        required_arrival_str = input_data.get("requiredArrival", "")
        if required_arrival_str:
            try:
                required_arrival = datetime.fromisoformat(required_arrival_str.replace("Z", ""))
            except (ValueError, TypeError):
                required_arrival = None

        remarks = str(input_data.get("remarks", "") or "")
        urgent = bool(input_data.get("urgent", False)) or any(k in remarks for k in ("加急", "urgent", "URGENT"))

        total_costs = [c["cost"]["total_cny"] for c in candidates]
        total_days = [c["timeline"]["total_days"] for c in candidates]
        min_cost = min(total_costs) if total_costs else 0
        max_cost = max(total_costs) if total_costs else 0
        min_days = min(total_days) if total_days else 0
        max_days = max(total_days) if total_days else 0
        cost_range = max_cost - min_cost
        days_range = max_days - min_days

        for c in candidates:
            cost_norm = (max_cost - c["cost"]["total_cny"]) / cost_range if cost_range > 0 else 1.0
            time_norm = (max_days - c["timeline"]["total_days"]) / days_range if days_range > 0 else 1.0
            if urgent:
                score = cost_norm * 0.3 + time_norm * 0.7
            else:
                score = cost_norm * 0.7 + time_norm * 0.3
            c["score"] = round(score * 100, 1)
            c["score_weights"] = {"cost": 0.3 if urgent else 0.7, "time": 0.7 if urgent else 0.3}

            meets_arrival = True
            if required_arrival is not None:
                try:
                    eta = datetime.strptime(c["timeline"]["eta"], "%Y-%m-%d")
                    meets_arrival = eta <= required_arrival
                except (ValueError, TypeError):
                    meets_arrival = False
            c["meets_arrival"] = meets_arrival

        self._cannot_meet_arrival = bool(required_arrival is not None and not any(c["meets_arrival"] for c in candidates))
        self._route_risk_warning = ""
        if self._cannot_meet_arrival:
            self._route_risk_warning = (
                f"所有方案预计到货时间均晚于客户要求到货时间（{required_arrival_str}），"
                "无法按客户约定时间到货，建议与客户确认延期或选择更早船期。"
            )

        if urgent or self._cannot_meet_arrival:
            # 条例2：按时效升序排列，时效相同再按评分降序
            candidates.sort(key=lambda x: (x["timeline"]["total_days"], -x["score"]))
        else:
            # 条例1：优先满足客户到货时间，再按综合评分降序
            candidates.sort(key=lambda x: (0 if x["meets_arrival"] else 1, -x["score"]))

        print(f"[候选生成] 共 {len(candidates)} 条路线（{len(factories)} 工厂 × {len(top_5_ports)} 始发港）")
        return candidates

    def _find_factories(self, product_type, dest_country):
        """
        查找符合条件的工厂（兼容旧接口，v3 实际使用 _find_factories_by_capacity）
        """
        # v3: 委托给产能过滤逻辑（无数量限制时使用知识库工厂）
        factories = self.kb.get_factory_by_product(product_type)
        if not factories:
            for name, info in self.kb.factory_info.items():
                factories.append({"name": name, "info": info})
        is_north_america = dest_country in NORTH_AMERICA
        if is_north_america:
            factories.sort(key=lambda x: 0 if x["info"]["region"] == "海外" else 1)
        return factories

    def _calculate_score_v3(self, info, cost, timeline, transport_pref, ocean_info):
        """
        v3 评分算法：基于总费用+时效+产能的综合评分（0-100）
        费用采用连续计分，避免同一档内费用差异被抹平
        """
        score = 50.0

        # 费用评分：连续计分，每¥1,000扣0.3分，封顶±20
        total_cost = cost["total_cny"]
        cost_score = 20.0 - (total_cost / 10000.0) * 3.0
        cost_score = max(-10.0, min(20.0, cost_score))
        score += cost_score

        # 海运费合约有效性
        if ocean_info.get("is_valid", False):
            score += 8
        elif ocean_info.get("rate_cny", 0) > 0:
            score += 3  # 有报价但过期

        # 时效评分
        total_days = timeline["total_days"]
        if total_days < 25:
            score += 10
        elif total_days < 40:
            score += 5
        elif total_days > 50:
            score -= 5

        # 产能评分
        total_cap = info.get("total_capacity", 0)
        if total_cap > 1000000:
            score += 10
        elif total_cap > 500000:
            score += 5

        # 运输偏好调整
        if transport_pref == "cost":
            score -= total_cost * 0.0005  # 成本优先：费用越低分越高
        elif transport_pref == "time":
            score -= total_days * 0.5

        return round(max(0, min(100, score)), 1)

    def _calculate_timeline(self, input_data, factory_name, dest_country, origin_port=''):
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
            inland_days_source = "overseas_estimate"
        else:
            from route_pricing import query_land_transit_time
            time_result = query_land_transit_time(factory_name, origin_port, 'direct')
            if time_result and time_result.get('days'):
                inland_days = max(1, int(round(time_result['days'])))
                inland_days_source = time_result.get('source', 'excel_time_analysis')
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
                inland_days_source = "province_estimate"

        # 海运天数
        ocean_days = int(self.kb.get_ocean_days(dest_country))
        if ocean_days <= 0:
            ocean_days = 30

        # ETD = max(货好时间 + 内陆运输天数, 期望船期)
        earliest_etd = cargo_ready + timedelta(days=inland_days)
        etd = max(earliest_etd, ship_schedule)

        # 等待天数（货物到港后等船的天数）
        waiting_days = (etd - earliest_etd).days
        if waiting_days < 0:
            waiting_days = 0

        # ETA = ETD + 海运天数
        eta = etd + timedelta(days=ocean_days)

        return {
            "cargo_ready": cargo_ready.strftime("%Y-%m-%d"),
            "ship_schedule": ship_schedule.strftime("%Y-%m-%d"),
            "inland_days": inland_days,
            "inland_days_source": inland_days_source,
            "ocean_days": ocean_days,
            "waiting_days": waiting_days,
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
        eligible_factory_names = []
        selected_origin_ports = []
        seen_ports = set()
        for c in candidates:
            if c["factory"] not in eligible_factory_names:
                eligible_factory_names.append(c["factory"])
            port_key = c["origin_port"]
            if port_key not in seen_ports:
                seen_ports.add(port_key)
                port_entry = dict(c.get("ocean_freight_info") or {
                    "port": port_key,
                    "port_cn": c.get("origin_port_cn", port_key),
                    "rate_cny": 0,
                    "rate_usd": 0,
                    "carrier": "",
                    "currency": "USD",
                    "is_valid": False,
                    "note": "无合约数据",
                })
                port_entry["dest_port"] = c["dest_port"]
                selected_origin_ports.append(port_entry)

        reasoning = self._generate_reasoning(input_data, primary, alternatives)

        return {
            "input": input_data,
            "primary": {
                "factory": primary["factory"],
                "factory_short": primary["factory_short"],
                "region": primary["region"],
                "departurePort": primary["origin_port"],
                "originPortCn": primary.get("origin_port_cn", primary["origin_port"]),
                "destPort": primary["dest_port"],
                "tradeTerm": primary["trade_term"],
                "tradeTermInfo": self.kb.trade_terms.get(primary["trade_term"], {}),
                "boxType": primary["box_type"],
                "boxTypes": primary["cost"].get("box_types", [primary["box_type"]]),
                "boxTypeCounts": primary["cost"].get("box_type_counts", {primary["box_type"]: 1}),
                "boxCount": primary["cost"].get("box_count", 1),
                "cost": primary["cost"],
                "timeline": primary["timeline"],
                "factoryInfo": primary["factory_info"],
                "carrier": primary.get("carrier", {}),
                "shippingLine": primary.get("shipping_line", {}),
                "shippingLines": primary.get("shipping_lines", {}),
                "oceanFreightInfo": primary.get("ocean_freight_info", {}),
                "score": primary["score"],
                "pricingSource": primary.get("pricing_source", "rule_engine"),
                "dataQuality": primary.get("data_quality", "medium"),
                "needFDA": input_data.get("destCountry") in FDA_COUNTRIES,
            },
            "alternatives": [
                {
                    "factory": a["factory"],
                    "factory_short": a["factory_short"],
                    "region": a["region"],
                    "departurePort": a["origin_port"],
                    "originPortCn": a.get("origin_port_cn", a["origin_port"]),
                    "destPort": a["dest_port"],
                    "tradeTerm": a["trade_term"],
                    "boxType": a["box_type"],
                    "cost": a["cost"],
                    "timeline": a["timeline"],
                    "carrier": a.get("carrier", {}),
                    "shippingLine": a.get("shipping_line", {}),
                    "oceanFreightInfo": a.get("ocean_freight_info", {}),
                    "score": a["score"],
                    "pricingSource": a.get("pricing_source", "rule_engine"),
                    "dataQuality": a.get("data_quality", "medium"),
                }
                for a in alternatives
            ],
            "allCandidates": [
                {
                    "factory": c["factory"],
                    "factoryShort": c["factory_short"],
                    "region": c["region"],
                    "departurePort": c["origin_port"],
                    "originPortCn": c.get("origin_port_cn", c["origin_port"]),
                    "destPort": c["dest_port"],
                    "tradeTerm": c["trade_term"],
                    "boxType": c["box_type"],
                    "totalCostCny": c["cost"]["total_cny"],
                    "totalCostUsd": c["cost"]["total_usd"],
                    "totalDays": c["timeline"]["total_days"],
                    "inlandDays": c["timeline"]["inland_days"],
                    "oceanDays": c["timeline"]["ocean_days"],
                    "score": c["score"],
                    "meetsArrival": c.get("meets_arrival", True),
                    "scoreWeights": c.get("score_weights", {}),
                    "pricingSource": c.get("pricing_source", "rule_engine"),
                    "dataQuality": c.get("data_quality", "medium"),
                    "originPortSource": c.get("origin_port_source", ""),
                    "originPortHistoryCount": c.get("origin_port_history_count", 0),
                    "carrier": c.get("carrier", {}).get("recommended", ""),
                    "shippingLine": c.get("shipping_line", {}).get("name", ""),
                    "oceanFreightInfo": c.get("ocean_freight_info", {}),
                    "costItems": c["cost"].get("items", []),
                    "dataQualityDetail": c["cost"].get("data_quality", {}),
                }
                for c in candidates
            ],
            "reasoning": reasoning,
            "risk_warning": self._route_risk_warning,
            "cannotMeetArrival": self._cannot_meet_arrival,
            "dataStats": self._get_data_stats(input_data.get("destCountry", "")),
            "eligibleFactories": len(eligible_factory_names),
            "eligibleFactoryNames": eligible_factory_names,
            "selectedOriginPorts": selected_origin_ports,
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
        reasons.append(f"费用方案含{fee_count}项明细，总费用约{cost:.0f} CNY（{cost * CNY_TO_USD:.0f} USD）")

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
        avg_cost = getattr(self.kb, 'country_avg_cost', {}).get(country)
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

        # 候选方案信息（所有 工厂×始发港×目的港 路线，按评分排序，取前8给LLM）
        candidate_info = []
        for i, c in enumerate(candidates[:8]):
            carrier = c.get('carrier', {})
            shipping = c.get('shipping_line', {})
            port_source = c.get('origin_port_source', '未知')
            port_history = c.get('origin_port_history_count', 0)
            port_source_label = {
                'factory_history': f'该工厂历史使用（{port_history}次）',
                'country_history': f'该运抵国历史使用（{port_history}次）',
                'default': '工厂默认港口',
            }.get(port_source, port_source)
            candidate_info.append(f"""
方案{i+1}：
  工厂：{c['factory']}（{c['factory_short']}，{c['region']}，{c['factory_info']['province']}）
  路线：{c['factory_short']} → {c['origin_port']} → {c['dest_port']}
  始发港来源：{port_source_label}
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
- 始发港数量：{kb_summary['total_origin_ports']}个（基于工厂配置默认港口）
- 海运费默认值：{kb_summary['avg_shipping_fee']} CNY（实际以合约报价为准）
- 货好到离港平均天数：{kb_summary['avg_cr_to_etd_days']}天

## 该运抵国数据统计
- 常用始发港：{data_stats.get('common_origin_ports', [])}
- 常用目的港：{data_stats.get('common_dest_ports', [])}
- 常用贸易条款：{data_stats.get('common_trade_terms', [])}
- 海运天数：{data_stats.get('ocean_days', {})}
- 平均总费用：{data_stats.get('avg_cost', {})}
- 费用明细中位数：{data_stats.get('fee_breakdown', {})}

## 候选方案
{''.join(candidate_info)}

## 请输出JSON格式的推荐结果
请从候选方案中选择最优方案，并给出详细推荐理由。**选择原则：综合评分相近（差距≤3分）时，必须优先选择总费用更低的方案；运输天数相同时，没有理由为同等时效付出更高费用。** 输出格式：
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

        # === LLM 质检：防止同分/近分情况下选择更贵的路线 ===
        if primary_idx > 0:
            cheapest = candidates[0]
            selected = candidates[primary_idx]
            cheapest_score = cheapest.get("score", 0)
            selected_score = selected.get("score", 0)
            cheapest_cost = cheapest["cost"]["total_cny"]
            selected_cost = selected["cost"]["total_cny"]
            cheapest_days = cheapest["timeline"]["total_days"]
            selected_days = selected["timeline"]["total_days"]

            score_diff = selected_score - cheapest_score
            cost_diff = selected_cost - cheapest_cost

            should_revert = False
            revert_reason = ""

            if score_diff <= 0 and cost_diff > 0:
                # 分数不更高但费用更高 — 没有理由选它
                should_revert = True
                revert_reason = f"分数相同({selected_score})但费用高CNY{cost_diff:,.0f}"
            elif 0 < score_diff <= 3 and selected_days >= cheapest_days and cost_diff > 0:
                # 分数略高但天数没优势 — 花钱买不到时效，不值
                should_revert = True
                revert_reason = f"评分仅高{score_diff}分但运输天数无优势(贵CNY{cost_diff:,.0f})"

            if should_revert:
                print(f"[LLM质检] 拒绝LLM选择(方案{primary_idx+1}), 回退到最便宜方案: {revert_reason}")
                primary_idx = 0

        result = self._rule_based_recommend(input_data, candidates)
        # 用LLM选择的方案替换
        if primary_idx > 0:
            selected = candidates[primary_idx]
            result["primary"]["factory"] = selected["factory"]
            result["primary"]["factory_short"] = selected["factory_short"]
            result["primary"]["region"] = selected["region"]
            result["primary"]["departurePort"] = selected["origin_port"]
            result["primary"]["originPortCn"] = selected.get("origin_port_cn", selected["origin_port"])
            result["primary"]["destPort"] = selected["dest_port"]
            result["primary"]["tradeTerm"] = selected["trade_term"]
            result["primary"]["boxType"] = selected["box_type"]
            result["primary"]["cost"] = selected["cost"]
            result["primary"]["timeline"] = selected["timeline"]
            result["primary"]["score"] = selected["score"]
            result["primary"]["carrier"] = selected.get("carrier", {})
            result["primary"]["shippingLine"] = selected.get("shipping_line", {})
            result["primary"]["shippingLines"] = selected.get("shipping_lines", {})
            # 重新排列 allCandidates：将 LLM 选中的主方案移到第一位，确保前端"最优"标签正确
            all_cands = result.get("allCandidates", [])
            if primary_idx < len(all_cands):
                selected_cand = all_cands.pop(primary_idx)
                all_cands.insert(0, selected_cand)
                result["allCandidates"] = all_cands
            # 重建 alternatives：从 candidates 中排除 LLM 选中的主方案
            new_alts = [c for i, c in enumerate(candidates) if i != primary_idx][:3]
            result["alternatives"] = [
                {
                    "factory": a["factory"],
                    "factory_short": a["factory_short"],
                    "region": a["region"],
                    "departurePort": a["origin_port"],
                    "originPortCn": a.get("origin_port_cn", a["origin_port"]),
                    "destPort": a["dest_port"],
                    "tradeTerm": a["trade_term"],
                    "boxType": a["box_type"],
                    "cost": a["cost"],
                    "timeline": a["timeline"],
                    "carrier": a.get("carrier", {}),
                    "shippingLine": a.get("shipping_line", {}),
                    "oceanFreightInfo": a.get("ocean_freight_info", {}),
                    "score": a["score"],
                    "pricingSource": a.get("pricing_source", "rule_engine"),
                    "dataQuality": a.get("data_quality", "medium"),
                }
                for a in new_alts
            ]

        # 添加LLM生成的理由
        result["reasoning"] = llm_result.get("reasoning", result["reasoning"])
        if self._cannot_meet_arrival:
            result["risk_warning"] = self._route_risk_warning
        else:
            result["risk_warning"] = llm_result.get("risk_warning", "")
        result["optimization_suggestion"] = llm_result.get("optimization_suggestion", "")
        result["llm_model"] = LLM_MODEL

        return result

    def estimate_toll_fee(self, province, origin_port, box_count, box_types, weight, volume):
        """调用LLM估算工厂自运高速费

        :param province: 工厂所在省份
        :param origin_port: 始发港
        :param box_count: 总箱数
        :param box_types: 箱型列表
        :param weight: 总重量(kg)
        :param volume: 总容积(m³)
        :return: 高速费估算（元）
        """
        if not LLM_ENABLED:
            # LLM不可用时回退到规则估算
            return self._rule_toll_fee(province, origin_port, box_count)

        prompt = f"""你是一位中国物流运输成本专家。请根据以下信息，估算工厂自运货物到港口的高速公路通行费。

## 运输信息
- 工厂所在省份：{province}
- 始发港：{origin_port}
- 总箱数：{box_count} 个集装箱
- 箱型：{', '.join(box_types) if isinstance(box_types, list) else str(box_types)}
- 总重量：{weight} kg
- 总体积：{volume} m³

## 计算要求
中国高速公路货车通行费标准：约 1.5-2.5 元/公里（根据省份和路段不同）。
请综合考虑以下因素：
1. 从{province}到{origin_port}的典型高速公路距离
2. 需要多少辆集装箱卡车（每辆约装1-2个40尺柜或2-3个20尺柜）
3. 各省高速公路费率差异（长三角约1.8元/km，山东约1.6元/km，中西部约2.0元/km）
4. 桥梁/隧道附加费（如有）

请输出一个JSON，格式严格如下，只返回JSON不要其他文字：
{{"distance_km": 450, "trucks": 3, "toll_per_km": 1.8, "bridge_tunnel_fee": 80, "total_toll": 2510, "reasoning": "安徽到上海约450km高速..."}}"""

        try:
            headers = {
                "Content-Type": "application/json",
                "Authorization": f"Bearer {LLM_API_KEY}",
            }
            payload = {
                "model": LLM_MODEL,
                "messages": [
                    {"role": "system", "content": "你是中国物流运输成本专家，擅长精确计算高速公路通行费。请严格按JSON格式输出结果。"},
                    {"role": "user", "content": prompt},
                ],
                "temperature": 0.1,
                "max_tokens": 500,
            }

            resp = requests.post(LLM_API_URL, json=payload, headers=headers, timeout=LLM_TIMEOUT)
            resp.raise_for_status()
            data = resp.json()
            content = data["choices"][0]["message"]["content"]

            # 解析LLM返回的JSON
            try:
                result = json.loads(content)
            except:
                match = re.search(r'\{.*\}', content, re.DOTALL)
                if match:
                    result = json.loads(match.group())
                else:
                    return self._rule_toll_fee(province, origin_port, box_count)

            total = int(float(result.get("total_toll", 0)))
            if total <= 0:
                return self._rule_toll_fee(province, origin_port, box_count)

            print(f"[LLM高速费] {province}->{origin_port}, {box_count}箱, "
                  f"距离={result.get('distance_km')}km, 卡车={result.get('trucks')}辆, "
                  f"高速费=CNY{total}, 理由: {result.get('reasoning', '')[:80]}")
            return total

        except Exception as e:
            print(f"[LLM高速费] 调用失败，回退规则引擎: {e}")
            return self._rule_toll_fee(province, origin_port, box_count)

    def _rule_toll_fee(self, province, origin_port, box_count):
        """规则引擎估算高速费（LLM不可用时的回退）"""
        province_toll_rates = {
            '山东': {'上海/SHANGHAI': (550, 1.6), '青岛/QINGDAO': (280, 1.6)},
            '安徽': {'上海/SHANGHAI': (420, 1.8), '青岛/QINGDAO': (580, 1.7)},
            '江西': {'上海/SHANGHAI': (620, 2.0), '青岛/QINGDAO': (850, 1.9)},
            '江苏': {'上海/SHANGHAI': (280, 1.8), '青岛/QINGDAO': (450, 1.7)},
            '上海': {'上海/SHANGHAI': (80, 1.8)},
            '越南': {'海防/HAIPHONG': (120, 0)},
            '印尼': {'勿拉湾/BELAWAN': (150, 0)},
        }

        default = (400, 1.8)
        prov_rates = province_toll_rates.get(province, {})
        distance, toll_rate = prov_rates.get(origin_port, default)

        # 估算卡车数量
        trucks = max(1, round(box_count / 2.5))
        total = round(distance * toll_rate + distance * 0.5) * trucks
        print(f"[规则高速费] {province}->{origin_port}, {box_count}箱, "
              f"距离={distance}km, 卡车={trucks}辆, 高速费~CNY{total}")
        return total

    # ===== LLM 路线费用估算（数据不足时的补充）=====

    def estimate_route_cost_llm(self, input_data, factory_name, origin_port, dest_port,
                                 trade_term, box_type, box_type_counts=None):
        """
        当规则引擎数据质量不足时，调用LLM估算整条路线的费用。

        LLM 会基于：
        - 工厂所在省份/地区 → 港口的陆运距离
        - 始发港 → 目的港的海运费率
        - 港杂费、报关费等标准费率
        来估算一个完整的费用明细。

        :return: dict 与 CostCalculator.calculate() 结构一致，额外含 pricing_source='llm'
        """
        if not LLM_ENABLED:
            return None

        product = input_data.get("productType", "")
        dest_country = input_data.get("destCountry", "")
        box_count = int(input_data.get("boxCount", 1) or 1)
        weight = float(input_data.get("weight", 0) or 0)
        volume = float(input_data.get("volume", 0) or 0)

        # 工厂信息
        factory_info = self.kb.factory_info.get(factory_name, {})
        province = factory_info.get("province", "未知")
        region = factory_info.get("region", "国内")

        # 箱型信息
        if box_type_counts and len(box_type_counts) > 1:
            bt_desc = ", ".join([f"{bt}×{qty}箱" for bt, qty in box_type_counts.items()])
            total_boxes = sum(box_type_counts.values())
        else:
            bt_desc = f"{box_type}×{box_count}箱"
            total_boxes = box_count

        prompt = f"""你是一位国际物流运输成本专家。请根据以下信息，估算一条完整的物流路线费用。

## 运输路线
- 工厂：{factory_name}（{province}，{region}）
- 始发港：{origin_port}
- 目的港：{dest_port}
- 运抵国：{dest_country}
- 贸易条款：{trade_term}
- 产品类型：{product}

## 货物信息
- 箱型与数量：{bt_desc}
- 总箱数：{total_boxes}
- 总重量：{weight} kg
- 总体积：{volume} CBM

## 需要估算的费用项（均为人民币 CNY）
1. 港杂费：始发港的港口杂费（按箱计算）
2. VGM费：约5元/箱
3. 舱单费：约55元/单（固定）
4. 陆运费：工厂到港口的拖车费（按箱计算，考虑{province}到{origin_port}的距离）
5. 报关费：出口报关费（按单计算）
6. 海运费：{origin_port}到{dest_port}的海运费（按箱计算）
{"7. 保险费：如贸易条款为CIF，按海运费的0.3%计算" if trade_term == "CIF" else ""}
{"7. 目的港费用：如贸易条款为DDP/DAP，按始发港杂费的80%计算" if trade_term in ("DDP", "DAP") else ""}

## 参考信息
- 中国主要港口到美国西海岸海运费约 1500-3000 USD/40HQ
- 中国到欧洲海运费约 2000-4000 USD/40HQ
- 中国到东南亚海运费约 500-1500 USD/40HQ
- 陆运费约 1500-3000 元/箱（视距离）
- 港杂费约 1500-3000 元/箱
- 汇率：1 USD ≈ {USD_TO_CNY} CNY

## 输出格式（严格JSON，不要其他文字）
{{
  "port_fee_per_box": 2500,
  "vgm_fee_per_box": 5,
  "manifest_fee": 55,
  "inland_fee_per_box": 2000,
  "customs_fee": 350,
  "ocean_fee_per_box": 18000,
  "insurance_fee": 54,
  "total_cny": 210000,
  "reasoning": "简要说明各项费用估算依据（100字以内）"
}}"""

        try:
            headers = {
                "Content-Type": "application/json",
                "Authorization": f"Bearer {LLM_API_KEY}",
            }
            payload = {
                "model": LLM_MODEL,
                "messages": [
                    {"role": "system", "content": "你是国际物流运输成本专家，擅长基于航线、距离、港口费率估算物流费用。请严格按JSON格式输出结果。"},
                    {"role": "user", "content": prompt},
                ],
                "temperature": 0.1,
                "max_tokens": 800,
            }

            resp = requests.post(LLM_API_URL, json=payload, headers=headers, timeout=LLM_TIMEOUT)
            resp.raise_for_status()
            data = resp.json()
            content = data["choices"][0]["message"]["content"]

            # 解析JSON
            try:
                result = json.loads(content)
            except json.JSONDecodeError:
                match = re.search(r'\{.*\}', content, re.DOTALL)
                if match:
                    result = json.loads(match.group())
                else:
                    return None

            # 构建与 CostCalculator 一致的结构
            port_fee = round(float(result.get("port_fee_per_box", 2500)) * total_boxes, 2)
            vgm_fee = round(float(result.get("vgm_fee_per_box", 5)) * total_boxes, 2)
            manifest_fee = float(result.get("manifest_fee", 55))
            inland_fee = round(float(result.get("inland_fee_per_box", 2000)) * total_boxes, 2)
            customs_fee = float(result.get("customs_fee", 350))
            ocean_fee = round(float(result.get("ocean_fee_per_box", 18000)) * total_boxes, 2)

            fee_items = [
                {"name": "港杂费", "category": "出口起运港港杂费",
                 "amount_cny": port_fee, "amount_usd": round(port_fee * CNY_TO_USD, 2),
                 "basis": f"LLM估算：单箱{result.get('port_fee_per_box', 2500)}元 × {total_boxes}箱"},
                {"name": "VGM费", "category": "海管家费用",
                 "amount_cny": vgm_fee, "amount_usd": round(vgm_fee * CNY_TO_USD, 2),
                 "basis": f"单箱5元 × {total_boxes}箱"},
                {"name": "舱单费", "category": "海管家费用",
                 "amount_cny": manifest_fee, "amount_usd": round(manifest_fee * CNY_TO_USD, 2),
                 "basis": "固定费用（按单）"},
                {"name": "陆运费", "category": "工厂到起运港拖车费",
                 "amount_cny": inland_fee, "amount_usd": round(inland_fee * CNY_TO_USD, 2),
                 "basis": f"LLM估算：单箱{result.get('inland_fee_per_box', 2000)}元 × {total_boxes}箱"},
                {"name": "报关费", "category": "出口报关单证费",
                 "amount_cny": customs_fee, "amount_usd": round(customs_fee * CNY_TO_USD, 2),
                 "basis": "固定费用（按单）"},
            ]

            if trade_term in ("CIF", "CFR", "DDP", "DAP"):
                fee_items.append({
                    "name": "海运费", "category": "出口海运费",
                    "amount_cny": ocean_fee, "amount_usd": round(ocean_fee * CNY_TO_USD, 2),
                    "basis": f"LLM估算：单箱{result.get('ocean_fee_per_box', 18000)}元 × {total_boxes}箱",
                })

            if trade_term == "CIF":
                insurance_fee = round(ocean_fee * 0.003, 2)
                fee_items.append({
                    "name": "保险费", "category": "保险费",
                    "amount_cny": insurance_fee, "amount_usd": round(insurance_fee * CNY_TO_USD, 2),
                    "basis": "海运费×0.3%",
                })

            if trade_term in ("DDP", "DAP"):
                dest_port_fee = round(float(result.get("port_fee_per_box", 2500)) * 0.8 * total_boxes, 2)
                fee_items.append({
                    "name": "目的港港杂费", "category": "出口目的港港杂费",
                    "amount_cny": dest_port_fee, "amount_usd": round(dest_port_fee * CNY_TO_USD, 2),
                    "basis": f"始发港杂费×80% × {total_boxes}箱",
                })

            total_cny = round(sum(item["amount_cny"] for item in fee_items), 2)
            total_usd = round(sum(item["amount_usd"] for item in fee_items), 2)

            print(f"[LLM路线估算] {factory_name}->{origin_port}->{dest_port}, "
                  f"{total_boxes}箱, 总费用=CNY{total_cny}, "
                  f"理由: {result.get('reasoning', '')[:80]}")

            return {
                "items": fee_items,
                "total_cny": total_cny,
                "total_usd": total_usd,
                "currency": "CNY",
                "box_type": box_type,
                "box_types": list(box_type_counts.keys()) if box_type_counts else [box_type],
                "box_type_counts": box_type_counts if box_type_counts else {box_type: total_boxes},
                "box_count": total_boxes,
                "trade_term": trade_term,
                "calc_details": [f"LLM估算：{result.get('reasoning', '')}"],
                "data_quality": {k: "llm" for k in ["port_fee", "vgm_fee", "manifest_fee",
                                                      "inland_fee", "customs_fee", "ocean_fee"]},
                "overall_quality": "llm",
                "pricing_source": "llm",
                "llm_reasoning": result.get("reasoning", ""),
                "note": f"LLM估算：共{len(fee_items)}项费用，{total_boxes}个集装箱",
            }

        except Exception as e:
            print(f"[LLM路线估算] 调用失败: {e}")
            return None
