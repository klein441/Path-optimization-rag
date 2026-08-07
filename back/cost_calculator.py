"""
费用计算器 — 基于真实历史数据动态计算各项物流费用
核心改进：费用随箱数/重量/体积/距离动态计算，而非固定中位数
"""
import math
import numpy as np
from config import USD_TO_CNY, CNY_TO_USD, BOX_TYPE_VOLUME
from knowledge_base import KnowledgeBase


class CostCalculator:
    """基于真实数据的动态费用计算器"""

    def __init__(self):
        self.kb = KnowledgeBase()
        self.kb.build()
        self._loader = self.kb._loader
        self._build_fee_rate_cache()

    def _build_fee_rate_cache(self):
        """构建费用费率缓存（基于历史数据统计）"""
        costs_df = self._loader.costs
        bl_df = self._loader.bl_waybill

        # 1. 各费用大类的单箱费率（按始发港分组）
        self.port_fee_rates = {}
        if not costs_df.empty and '费用大类' in costs_df.columns and '含税金额' in costs_df.columns:
            costs_df['含税金额'] = pd.to_numeric(costs_df['含税金额'], errors='coerce')
            # 按费用大类和始发港统计单箱费率
            for fee_class in costs_df['费用大类'].unique():
                subset = costs_df[costs_df['费用大类'] == fee_class]['含税金额'].dropna()
                subset = subset[(subset > 0) & (subset < 100000)]
                if len(subset) >= 5:
                    self.port_fee_rates[fee_class] = float(np.median(subset))

        # 2. 各航线海运费率（始发港→运抵国）
        self.route_ocean_rates = {}
        if not bl_df.empty:
            # 从提单运单提取海运费数据
            if '始发港' in bl_df.columns and '运抵国' in bl_df.columns:
                for (origin, dest), group in bl_df.groupby(['始发港', '运抵国']):
                    if '_total_fee_cny' in group.columns:
                        fees = group['_total_fee_cny'].dropna()
                        fees = fees[(fees > 0) & (fees < 500000)]
                        if len(fees) >= 3:
                            self.route_ocean_rates[(str(origin), str(dest))] = {
                                'median': float(np.median(fees)),
                                'mean': float(np.mean(fees)),
                                'count': len(fees),
                            }

        # 3. 各工厂到港口的陆运费率
        self.factory_inland_rates = {}
        container_df = self._loader.container_waybill
        if not container_df.empty and '运输方式' in container_df.columns:
            # 统计拖车运输的费率
            trailer_mask = container_df['运输方式'].str.contains('拖车|直拖', na=False)
            if trailer_mask.any():
                trailer_data = container_df[trailer_mask]
                if '箱数' in trailer_data.columns:
                    self.trailer_base_rate = 2000  # 拖车基础费率（元/箱）
                else:
                    self.trailer_base_rate = 2000
            else:
                self.trailer_base_rate = 2000
        else:
            self.trailer_base_rate = 2000

        # 4. 海运费收入表统计
        self.shipping_rates = {}
        sf_df = self._loader.shipping_fee
        if not sf_df.empty:
            for col in ['海运费', '客户海运费', '海运费收入']:
                if col in sf_df.columns:
                    vals = pd.to_numeric(sf_df[col], errors='coerce').dropna()
                    vals = vals[(vals > 0) & (vals < 500000)]
                    if len(vals) >= 5:
                        self.shipping_rates[col] = float(np.median(vals))

    def calculate(self, input_data, factory_name, origin_port, dest_port, trade_term, box_type="40HQ", box_type_counts=None):
        """
        基于真实数据动态计算费用
        :param input_data: 用户输入 (productType, destCountry, boxCount, weight, volume, cargoReady, shipSchedule)
        :param factory_name: 工厂全称
        :param origin_port: 始发港
        :param dest_port: 目的港
        :param trade_term: 贸易条款
        :param box_type: 集装箱箱型（单箱型时的默认值）
        :param box_type_counts: 各箱型数量字典，如 {"40HQ": 5, "20GP": 3}（可选，支持多箱型）
        :return: 费用明细字典
        """
        dest_country = input_data.get("destCountry", "")
        volume = float(input_data.get("volume", 0) or 0)
        weight = float(input_data.get("weight", 0) or 0)
        box_count = max(1, int(float(input_data.get("boxCount", 1) or 1)))

        # 判断是否为多箱型模式
        is_multi_box = box_type_counts and len(box_type_counts) > 1
        if is_multi_box:
            # 多箱型：总箱数=各箱型数量之和
            actual_boxes = sum(box_type_counts.values())
            # 使用第一个箱型作为默认箱型（用于陆运费、港杂费等按箱计算的费用）
            primary_box_type = list(box_type_counts.keys())[0]
        else:
            # 单箱型：原有逻辑
            actual_boxes = self._estimate_actual_boxes(volume, box_count, box_type)
            primary_box_type = box_type
            box_type_counts = {box_type: actual_boxes}

        # 获取该运抵国的历史费用统计
        country_fees = self.kb.get_fee_breakdown(dest_country)

        # 计算各费用项
        fee_items = []
        calc_details = []

        # 1. 港杂费（按箱数计算）
        port_fee_per_box = self._get_port_fee_rate("出口起运港港杂费", origin_port, country_fees)
        port_fee = round(port_fee_per_box * actual_boxes, 2)
        fee_items.append({
            "name": "港杂费",
            "category": "出口起运港港杂费",
            "amount_cny": port_fee,
            "amount_usd": round(port_fee * CNY_TO_USD, 2),
            "basis": f"单箱{port_fee_per_box}元 × {actual_boxes}箱",
        })
        calc_details.append(f"港杂费：{port_fee_per_box}元/箱 × {actual_boxes}箱 = {port_fee}元")

        # 2. VGM费（按箱数计算）
        vgm_per_box = 5.0  # VGM费约5元/箱
        vgm_fee = round(vgm_per_box * actual_boxes, 2)
        fee_items.append({
            "name": "VGM费",
            "category": "海管家费用",
            "amount_cny": vgm_fee,
            "amount_usd": round(vgm_fee * CNY_TO_USD, 2),
            "basis": f"单箱{vgm_per_box}元 × {actual_boxes}箱",
        })
        calc_details.append(f"VGM费：{vgm_per_box}元/箱 × {actual_boxes}箱 = {vgm_fee}元")

        # 3. 舱单费（按单计算，固定）
        manifest_fee = 55.0
        fee_items.append({
            "name": "舱单费",
            "category": "海管家费用",
            "amount_cny": manifest_fee,
            "amount_usd": round(manifest_fee * CNY_TO_USD, 2),
            "basis": "固定费用（按单）",
        })
        calc_details.append(f"舱单费：固定55元/单")

        # 4. ICS2费（欧盟入境申报费，仅欧洲国家）
        european_countries = ["德国", "荷兰", "英国", "法国", "意大利", "西班牙", "比利时", "波兰",
                              "瑞典", "芬兰", "丹麦", "奥地利", "爱尔兰", "葡萄牙", "希腊",
                              "捷克", "罗马尼亚", "匈牙利", "斯洛文尼亚", "爱沙尼亚", "立陶宛",
                              "克罗地亚", "拉脱维亚", "保加利亚", "斯洛伐克", "卢森堡", "马耳他",
                              "塞浦路斯", "挪威", "瑞士"]
        if dest_country in european_countries:
            ics2_fee = 70.0
            fee_items.append({
                "name": "ICS2费",
                "category": "海管家费用",
                "amount_cny": ics2_fee,
                "amount_usd": round(ics2_fee * CNY_TO_USD, 2),
                "basis": "欧盟入境申报（按单）",
            })
            calc_details.append(f"ICS2费：欧盟入境申报70元/单")

        # 5. 陆运费（拖车费，按距离×箱数计算，使用主要箱型计算单箱费率）
        inland_per_box = self._calculate_inland_rate(factory_name, origin_port, weight, primary_box_type)
        inland_fee = round(inland_per_box * actual_boxes, 2)
        fee_items.append({
            "name": "陆运费",
            "category": "出口起运港拖车费",
            "amount_cny": inland_fee,
            "amount_usd": round(inland_fee * CNY_TO_USD, 2),
            "basis": f"单箱{inland_per_box}元 × {actual_boxes}箱",
        })
        calc_details.append(f"陆运费：{inland_per_box}元/箱 × {actual_boxes}箱 = {inland_fee}元")

        # 6. 报关费（按单计算，固定，截断处理）
        customs_fee = self._calculate_customs_fee(origin_port)
        fee_items.append({
            "name": "报关费",
            "category": "出口报关单证费",
            "amount_cny": customs_fee,
            "amount_usd": round(customs_fee * CNY_TO_USD, 2),
            "basis": "固定费用（按单）",
        })
        calc_details.append(f"报关费：{customs_fee}元/单")

        # 7. 海运费（按箱数计算，支持多箱型分别计算并累加）
        ocean_fee = 0
        ocean_details_parts = []
        for bt, qty in box_type_counts.items():
            bt_per_box = self._calculate_ocean_rate(dest_country, origin_port, bt)
            bt_subtotal = round(bt_per_box * qty, 2)
            ocean_fee += bt_subtotal
            ocean_details_parts.append(f"{bt}：{bt_per_box}元/箱 × {qty}箱 = {bt_subtotal}元")

        ocean_fee = round(ocean_fee, 2)
        if trade_term in ("CIF", "CFR", "DDP", "DAP"):
            ocean_basis = " + ".join([f"{bt} {self._calculate_ocean_rate(dest_country, origin_port, bt)}元/箱×{qty}箱" for bt, qty in box_type_counts.items()])
            fee_items.append({
                "name": "海运费" + ("（多箱型合计）" if is_multi_box else ""),
                "category": "出口海运费",
                "amount_cny": ocean_fee,
                "amount_usd": round(ocean_fee * CNY_TO_USD, 2),
                "basis": ocean_basis if is_multi_box else f"单箱{ocean_fee/actual_boxes:.0f}元 × {actual_boxes}箱",
            })
            calc_details.append(f"海运费：{' + '.join(ocean_details_parts)} = {ocean_fee}元")

        # 8. 保险费（仅CIF，基于海运费计算）
        if trade_term == "CIF":
            insurance_fee = round(ocean_fee * 0.003, 2)
            fee_items.append({
                "name": "保险费",
                "category": "保险费",
                "amount_cny": insurance_fee,
                "amount_usd": round(insurance_fee * CNY_TO_USD, 2),
                "basis": f"海运费×0.3%",
            })
            calc_details.append(f"保险费：{ocean_fee}元 × 0.3% = {insurance_fee}元")

        # 9. 目的港费用（仅DDP/DAP）
        if trade_term in ("DDP", "DAP"):
            dest_port_fee = round(port_fee_per_box * 0.8 * actual_boxes, 2)
            fee_items.append({
                "name": "目的港港杂费",
                "category": "出口目的港港杂费",
                "amount_cny": dest_port_fee,
                "amount_usd": round(dest_port_fee * CNY_TO_USD, 2),
                "basis": f"始发港杂费×80% × {actual_boxes}箱",
            })
            calc_details.append(f"目的港港杂费：{port_fee_per_box}元×80% × {actual_boxes}箱 = {dest_port_fee}元")

        # 汇总
        total_cny = round(sum(item["amount_cny"] for item in fee_items), 2)
        total_usd = round(sum(item["amount_usd"] for item in fee_items), 2)

        return {
            "items": fee_items,
            "total_cny": total_cny,
            "total_usd": total_usd,
            "currency": "CNY",
            "box_type": primary_box_type,
            "box_types": list(box_type_counts.keys()),  # 所有箱型列表
            "box_type_counts": box_type_counts,  # 各箱型数量
            "box_count": actual_boxes,
            "trade_term": trade_term,
            "calc_details": calc_details,
            "note": f"基于历史费率动态计算：共{len(fee_items)}项费用，{actual_boxes}个集装箱"
                    + (f"（{len(box_type_counts)}种箱型）" if is_multi_box else ""),
        }

    def _get_port_fee_rate(self, fee_category, origin_port, country_fees):
        """获取单箱港口费率（基于历史数据）"""
        # 优先使用该运抵国的历史数据
        if fee_category in country_fees:
            return country_fees[fee_category]["median"]

        # 使用全局费用统计
        if fee_category in self.port_fee_rates:
            return self.port_fee_rates[fee_category]

        # 回退：根据港口类型返回默认值
        port_defaults = {
            "青岛/QINGDAO": 2800,
            "上海/SHANGHAI": 2500,
            "宁波/NINGBO": 2600,
            "天津/TAINJIN": 2700,
            "海防/HAIPHONG": 1500,
            "勿拉湾/BELAWAN": 1800,
        }
        return port_defaults.get(origin_port, 2500)

    def _calculate_inland_rate(self, factory_name, origin_port, weight, box_type):
        """
        计算单箱陆运费率
        基于工厂到港口的距离、重量、箱型综合评估
        """
        # 基础费率（根据始发港）
        port_base_rates = {
            "青岛/QINGDAO": 2200,
            "上海/SHANGHAI": 1800,
            "宁波/NINGBO": 2000,
            "天津/TAINJIN": 2100,
            "海防/HAIPHONG": 1200,
            "勿拉湾/BELAWAN": 1500,
        }
        base_rate = port_base_rates.get(origin_port, 2000)

        # 工厂距离调整（内陆工厂加价）
        distance_adj = self._get_factory_distance_adjustment(factory_name, origin_port)

        # 重量调整（超重加价）
        weight_adj = 1.0
        if weight > 20000:
            weight_adj = 1.1
        elif weight > 15000:
            weight_adj = 1.05

        # 箱型调整
        box_type_adj = {
            "20GP": 0.8,
            "40GP": 1.0,
            "40HQ": 1.05,
            "40HC": 1.05,
            "45HQ": 1.15,
        }
        type_adj = box_type_adj.get(box_type, 1.0)

        return round(base_rate * distance_adj * weight_adj * type_adj, 2)

    def _get_factory_distance_adjustment(self, factory_name, origin_port):
        """根据工厂到港口的距离返回调整系数"""
        # 工厂到港口的大致距离（公里）
        factory_port_distances = {
            # 山东工厂 → 青岛港
            "山东英科医疗制品有限公司": {"青岛/QINGDAO": 1.0, "上海/SHANGHAI": 1.3},
            "英科医疗科技股份有限公司": {"青岛/QINGDAO": 1.0, "上海/SHANGHAI": 1.3},
            # 安徽工厂 → 上海/青岛
            "安徽英科医疗用品有限公司": {"青岛/QINGDAO": 1.3, "上海/SHANGHAI": 1.0},
            "安庆英科医疗有限公司": {"青岛/QINGDAO": 1.4, "上海/SHANGHAI": 1.0},
            # 江西工厂 → 上海
            "江西英科医疗有限公司": {"青岛/QINGDAO": 1.5, "上海/SHANGHAI": 1.0},
            # 江苏工厂 → 上海
            "江苏英科医疗制品有限公司": {"青岛/QINGDAO": 1.3, "上海/SHANGHAI": 1.0},
            # 上海本地
            "上海英恩国际贸易有限公司": {"上海/SHANGHAI": 0.9, "青岛/QINGDAO": 1.4},
            "上海英科医疗用品有限公司": {"上海/SHANGHAI": 0.9, "青岛/QINGDAO": 1.4},
            # 海外工厂
            "BASIC INTERNATIONAL VIET NAM CO..LTD": {"海防/HAIPHONG": 1.0},
            "INTCO MEDICAL TECHNOLOGY VIET NAM COMPANY LIMITED": {"海防/HAIPHONG": 1.0},
            "PT BASIC INTERNATIONAL SUMATERA": {"勿拉湾/BELAWAN": 1.0},
        }

        if factory_name in factory_port_distances:
            distances = factory_port_distances[factory_name]
            return distances.get(origin_port, 1.2)

        # 未知工厂，根据省份判断
        province_hints = {
            "安徽": {"青岛/QINGDAO": 1.3, "上海/SHANGHAI": 1.0},
            "山东": {"青岛/QINGDAO": 1.0, "上海/SHANGHAI": 1.3},
            "江西": {"青岛/QINGDAO": 1.5, "上海/SHANGHAI": 1.0},
            "江苏": {"青岛/QINGDAO": 1.3, "上海/SHANGHAI": 1.0},
            "上海": {"上海/SHANGHAI": 0.9},
            "越南": {"海防/HAIPHONG": 1.0},
            "印尼": {"勿拉湾/BELAWAN": 1.0},
        }

        # 从工厂名推断省份
        factory_province = self._infer_province(factory_name)
        if factory_province in province_hints:
            return province_hints[factory_province].get(origin_port, 1.2)

        return 1.2

    def _infer_province(self, factory_name):
        """从工厂名推断所在省份"""
        mapping = {
            "安徽英科": "安徽",
            "安庆英科": "安徽",
            "山东英科": "山东",
            "江西英科": "江西",
            "江苏英科": "江苏",
            "上海英科": "上海",
            "英科医疗科技": "山东",
            "英恩国际": "上海",
            "VIET NAM": "越南",
            "印尼": "印尼",
            "SUMATERA": "印尼",
        }
        for keyword, province in mapping.items():
            if keyword in factory_name:
                return province
        return ""

    def _calculate_customs_fee(self, origin_port):
        """计算报关费（固定，按港口略有差异）"""
        port_customs_fees = {
            "青岛/QINGDAO": 350,
            "上海/SHANGHAI": 380,
            "宁波/NINGBO": 330,
            "天津/TAINJIN": 340,
            "海防/HAIPHONG": 300,
            "勿拉湾/BELAWAN": 300,
        }
        return port_customs_fees.get(origin_port, 350)

    def _calculate_ocean_rate(self, dest_country, origin_port, box_type):
        """
        计算单箱海运费率（基于历史数据动态计算）
        """
        # 1. 查找该航线的历史费率
        route_key = (origin_port, dest_country)
        if route_key in self.route_ocean_rates:
            route_data = self.route_ocean_rates[route_key]
            base_rate = route_data['median']
        else:
            # 2. 查找海运费收入表的中位数
            if '海运费' in self.shipping_rates:
                base_rate = self.shipping_rates['海运费']
            else:
                base_rate = 2500

        # 3. 距离调整系数（基于海运天数估算）
        distance_mult = self._get_distance_multiplier(dest_country)

        # 4. 箱型调整
        box_mult = self._get_box_type_multiplier(box_type)

        return round(base_rate * distance_mult * box_mult, 2)

    def _get_distance_multiplier(self, country):
        """根据运抵国获取距离系数（基于海运天数）"""
        # 近洋（5-12天）
        near = ["日本", "韩国", "新加坡", "泰国", "越南", "马来西亚", "菲律宾", "印度尼西亚", "文莱", "缅甸"]
        # 中东/南亚（15-25天）
        medium_near = ["阿联酋", "沙特阿拉伯", "阿曼", "巴林", "科威特", "约旦", "印度", "巴基斯坦", "孟加拉"]
        # 澳洲/新西兰（20-25天）
        medium = ["澳大利亚", "新西兰"]
        # 北美（16-20天）
        far = ["美国", "加拿大", "墨西哥"]
        # 欧洲（30-35天）
        europe = ["德国", "荷兰", "英国", "法国", "意大利", "西班牙", "比利时", "波兰",
                   "瑞典", "芬兰", "丹麦", "奥地利", "爱尔兰", "葡萄牙", "希腊", "捷克",
                   "挪威", "瑞士"]
        # 南美（35-45天）
        very_far = ["巴西", "阿根廷", "智利", "秘鲁", "哥伦比亚", "厄瓜多尔"]
        # 非洲（28-35天）
        africa = ["南非", "埃及", "肯尼亚", "尼日利亚", "摩洛哥"]

        if country in near:
            return 0.5
        elif country in medium_near:
            return 0.7
        elif country in medium:
            return 0.8
        elif country in far:
            return 1.2
        elif country in europe:
            return 1.0
        elif country in very_far:
            return 1.5
        elif country in africa:
            return 1.3
        return 1.0

    def _get_box_type_multiplier(self, box_type):
        """获取箱型系数"""
        multipliers = {
            "20GP": 0.6,
            "20HQ": 0.65,
            "40GP": 1.0,
            "40HQ": 1.05,
            "40HC": 1.05,
            "40NOR": 0.9,
            "45HQ": 1.15,
            "LCL": 0.3,
        }
        return multipliers.get(box_type, 1.0)

    def _estimate_actual_boxes(self, volume, box_count, box_type):
        """估算实际需要的集装箱数量"""
        # 如果用户已经指定了箱数，优先使用
        if box_count > 1:
            return box_count

        # 根据体积估算
        box_vol = BOX_TYPE_VOLUME.get(box_type, 67.0)
        if box_vol == 0:  # LCL
            return 1
        return max(1, math.ceil(volume / box_vol))

    def suggest_box_type(self, volume, weight):
        """根据体积和重量推荐集装箱箱型"""
        if volume <= 0:
            return "40HQ"
        if volume < 15:
            return "LCL"
        elif volume <= 33:
            return "20GP"
        elif volume <= 67:
            return "40GP"
        elif volume <= 76:
            return "40HQ"
        else:
            return "40HQ"

    def estimate_container_count(self, volume, box_type="40HQ"):
        """估算需要的集装箱数量"""
        box_vol = BOX_TYPE_VOLUME.get(box_type, 76.0)
        if box_vol == 0:
            return 1
        return max(1, math.ceil(volume / box_vol))


# 兼容旧版 import
import pandas as pd