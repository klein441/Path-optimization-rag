"""
知识库 — 基于真实数据统计构建的物流知识库
包含：工厂产能、港口映射、路线统计、费用基准、贸易条款、箱型信息
"""
import numpy as np
from data_loader import DataLoader
from config import FACTORY_SHORT, FACTORY_REGION, NORTH_AMERICA, FDA_COUNTRIES, BOX_TYPE_VOLUME


class KnowledgeBase:
    """物流知识库（基于真实数据）"""

    _instance = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._built = False
        return cls._instance

    def build(self):
        """构建知识库（单例模式）"""
        if self._built:
            return
        loader = DataLoader()
        loader.load_all()
        self._loader = loader
        self._build_factory_info()
        self._build_port_routes()
        self._build_fee_base()
        self._build_trade_terms()
        self._build_box_types()
        self._build_timeline_stats()
        self._build_shipping_fee_stats()
        self._build_carrier_stats()
        self._build_shipping_lines()
        self._built = True

    # ===== 工厂信息 =====
    def _build_factory_info(self):
        """基于各基地产能表构建工厂信息"""
        cap_df = self._loader.factory_capacity
        self.factory_capacity = {}
        for _, row in cap_df.iterrows():
            name = row['基地']
            pvc_cap = row.get('PVC数量（千只数）', 0)
            nitrile_cap = row.get('丁腈数量（千只数）', 0)
            self.factory_capacity[name] = {
                "pvc_capacity": float(pvc_cap),
                "nitrile_capacity": float(nitrile_cap),
                "total_capacity": float(row.get('总', 0)),
            }

        # 计算产能占比
        total_pvc = sum(f["pvc_capacity"] for f in self.factory_capacity.values())
        total_nitrile = sum(f["nitrile_capacity"] for f in self.factory_capacity.values())
        for name in self.factory_capacity:
            self.factory_capacity[name]["pvc_share"] = round(self.factory_capacity[name]["pvc_capacity"] / total_pvc * 100, 1) if total_pvc else 0
            self.factory_capacity[name]["nitrile_share"] = round(self.factory_capacity[name]["nitrile_capacity"] / total_nitrile * 100, 1) if total_nitrile else 0

        # 合并工厂区域信息
        self.factory_info = {}
        for name, cap in self.factory_capacity.items():
            region = FACTORY_REGION.get(name, {"region": "国内", "province": "未知", "default_port": "青岛/QINGDAO"})
            short = FACTORY_SHORT.get(name, name)
            self.factory_info[name] = {
                "full_name": name,
                "short_name": short,
                "region": region["region"],
                "province": region["province"],
                "default_port": region["default_port"],
                "pvc_capacity": cap["pvc_capacity"],
                "nitrile_capacity": cap["nitrile_capacity"],
                "pvc_share": cap["pvc_share"],
                "nitrile_share": cap["nitrile_share"],
                "total_capacity": cap["total_capacity"],
            }

        # 基于物料行数据，统计各工厂实际生产的产品类型
        material_df = self._loader.material_line
        if '发货车间' in material_df.columns and '物料名称' in material_df.columns:
            factory_products = {}
            for _, row in material_df.iterrows():
                workshop = str(row.get('发货车间', ''))
                material = str(row.get('物料名称', ''))
                if workshop and workshop != 'nan':
                    # 从车间名提取工厂（如"安庆丁腈二车间6#线" -> "安庆英科医疗有限公司"）
                    factory = self._match_factory_from_workshop(workshop)
                    if factory:
                        if factory not in factory_products:
                            factory_products[factory] = set()
                        if '丁腈' in material:
                            factory_products[factory].add('丁腈手套')
                        elif 'PVC' in material or 'pvc' in material.lower():
                            factory_products[factory].add('PVC手套')
                        elif 'PE' in material or 'pe' in material.lower():
                            factory_products[factory].add('PE产品')

            for name in self.factory_info:
                products = list(factory_products.get(name, []))
                # 产能兜底：如果物料行未匹配到，但产能表显示有该产品产能，则补充
                if not products:
                    cap = self.factory_capacity.get(name, {})
                    if cap.get("pvc_capacity", 0) > 1000:
                        products.append("PVC手套")
                    if cap.get("nitrile_capacity", 0) > 1000:
                        products.append("丁腈手套")
                self.factory_info[name]["products"] = products

    def _match_factory_from_workshop(self, workshop):
        """从车间名匹配工厂名"""
        mapping = {
            "安庆": "安庆英科医疗有限公司",
            "安徽": "安徽英科医疗用品有限公司",
            "江西": "江西英科医疗有限公司",
            "淄博": "山东英科医疗制品有限公司",
            "青州": "山东英科医疗制品有限公司",
            "山东": "山东英科医疗制品有限公司",
        }
        for key, factory in mapping.items():
            if key in workshop:
                return factory
        return None

    # ===== 港口与路线 =====
    def _build_port_routes(self):
        """基于提单运单构建港口与路线统计"""
        df = self._loader.bl_waybill

        # 检查必要列是否存在
        has_country = '运抵国' in df.columns
        has_origin = '始发港' in df.columns
        has_dest = '目的港' in df.columns
        has_term = '贸易条款' in df.columns
        has_factory = '发货工厂' in df.columns

        # 运抵国 -> 目的港映射
        self.country_dest_ports = {}
        self.country_origin_ports = {}
        self.country_trade_terms = {}
        self.all_countries = []

        if has_country:
            countries = df['运抵国'].dropna().unique()
            self.all_countries = sorted(countries.tolist())
            for country in countries:
                if has_dest:
                    self.country_dest_ports[country] = self._loader.get_country_dest_ports(country)
                if has_origin:
                    self.country_origin_ports[country] = self._loader.get_country_origin_ports(country)
                if has_term:
                    self.country_trade_terms[country] = self._loader.get_country_trade_terms(country)

        # 工厂 -> 始发港映射
        self.factory_ports = {}
        if has_factory and has_origin:
            for factory in self.factory_info:
                routes = self._loader.get_factory_routes(factory)
                if not routes.empty and '始发港' in routes.columns:
                    ports = routes['始发港'].dropna().value_counts()
                    self.factory_ports[factory] = [{"port": idx, "count": int(cnt)} for idx, cnt in ports.items()]

        # 所有始发港列表
        self.all_origin_ports = []
        if has_origin:
            self.all_origin_ports = sorted(df['始发港'].dropna().unique().tolist())

    # ===== 费用基准 =====
    def _build_fee_base(self):
        """基于费用明细和出口销售订单构建费用基准"""
        # 1. 从出口销售订单中解析各运抵国的费用统计
        self.country_fee_stats = {}
        for country in self.all_countries:
            stats = self._loader.get_fee_stats_by_country(country)
            if stats:
                self.country_fee_stats[country] = stats

        # 2. 从费用明细表构建全局费用统计
        costs_df = self._loader.costs
        self.global_fee_stats = {}
        if '费用大类' in costs_df.columns and '含税金额' in costs_df.columns:
            for fee_class, group in costs_df.groupby('费用大类'):
                amounts = group['含税金额'].dropna()
                amounts = amounts[amounts > 0]
                if len(amounts) > 0:
                    median_val = float(np.median(amounts))
                    mean_val = float(np.mean(amounts))
                    # 使用中位数（比均值更抗异常值）
                    self.global_fee_stats[fee_class] = {
                        "count": len(amounts),
                        "mean": round(mean_val, 2),
                        "median": round(median_val, 2),
                        "min": round(float(np.min(amounts)), 2),
                        "max": round(float(np.max(amounts)), 2),
                    }

        # 3. TMS费用类型定义
        self.tms_fee_types = {}
        tms_df = self._loader.tms_fee_type
        if '费用大类' in tms_df.columns and '费用类型' in tms_df.columns:
            for _, row in tms_df.iterrows():
                cat = row['费用大类']
                ftype = row['费用类型']
                if cat not in self.tms_fee_types:
                    self.tms_fee_types[cat] = []
                self.tms_fee_types[cat].append(ftype)

        # 4. 各运抵国平均总费用
        self.country_avg_cost = {}
        for country in self.all_countries:
            cost_info = self._loader.get_country_avg_cost(country)
            if cost_info:
                self.country_avg_cost[country] = cost_info

    # ===== 贸易条款 =====
    def _build_trade_terms(self):
        """贸易条款知识"""
        self.trade_terms = {
            "FOB": {
                "full": "FOB (Free On Board)",
                "desc": "卖方负责货物越过船舷前的一切费用和风险，买方承担海运及目的港费用",
                "seller_resp": "工厂→装船",
                "cost_scope": "内陆运输+报关+装船",
            },
            "CIF": {
                "full": "CIF (Cost, Insurance & Freight)",
                "desc": "卖方承担运至目的港的运费和保险费，买方承担目的港后费用",
                "seller_resp": "工厂→目的港",
                "cost_scope": "内陆+海运+保险+报关",
            },
            "CFR": {
                "full": "CFR (Cost and Freight)",
                "desc": "卖方承担运至目的港的运费，买方承担保险和目的港后费用",
                "seller_resp": "工厂→目的港",
                "cost_scope": "内陆+海运+报关",
            },
            "DDP": {
                "full": "DDP (Delivered Duty Paid)",
                "desc": "卖方承担运至买方指定地点的全部费用，包括进口关税和税费",
                "seller_resp": "工厂→买方仓库",
                "cost_scope": "全程费用含关税",
            },
            "FCA": {
                "full": "FCA (Free Carrier)",
                "desc": "卖方在指定地点将货物交给买方指定的承运人",
                "seller_resp": "工厂→承运人",
                "cost_scope": "内陆运输+报关",
            },
            "EXW": {
                "full": "EXW (Ex Works)",
                "desc": "卖方在其所在地（工厂/仓库）将货物交给买方处置",
                "seller_resp": "仅工厂交货",
                "cost_scope": "无（买方承担全部）",
            },
            "DAP": {
                "full": "DAP (Delivered at Place)",
                "desc": "卖方将货物运至指定目的地交货",
                "seller_resp": "工厂→指定地点",
                "cost_scope": "内陆+海运+清关（不含关税）",
            },
        }

    # ===== 箱型信息 =====
    def _build_box_types(self):
        """集装箱箱型信息"""
        self.box_types = BOX_TYPE_VOLUME
        self.box_type_stats = self._loader.get_box_type_stats()
        self.container_transport_modes = self._loader.get_container_transport_mode_stats()

    # ===== 时间统计 =====
    def _build_timeline_stats(self):
        """基于历史数据构建运输时间统计"""
        df = self._loader.bl_waybill

        # 地理估算海运天数（历史数据ETD->ETA不可靠时的回退值）
        geo_ocean_days = {
            "日本": 7, "韩国": 6, "新加坡": 12, "泰国": 10, "越南": 5, "马来西亚": 10, "菲律宾": 10,
            "美国": 18, "加拿大": 17, "墨西哥": 20,
            "德国": 32, "荷兰": 30, "英国": 33, "法国": 31, "意大利": 34, "西班牙": 33,
            "比利时": 31, "波兰": 33, "瑞典": 33, "芬兰": 34, "丹麦": 32, "奥地利": 34,
            "爱尔兰": 33, "葡萄牙": 33, "希腊": 32, "捷克": 33, "挪威": 33, "瑞士": 33,
            "澳大利亚": 22, "新西兰": 25, "印度尼西亚": 10, "文莱": 12,
            "阿联酋": 20, "沙特阿拉伯": 22, "阿曼": 21, "巴林": 22, "科威特": 22, "约旦": 23,
            "印度": 18, "巴基斯坦": 20, "孟加拉": 18, "缅甸": 12,
            "巴西": 38, "阿根廷": 40, "智利": 36, "秘鲁": 37, "哥伦比亚": 35,
            "南非": 30, "埃及": 25, "肯尼亚": 28, "尼日利亚": 30, "摩洛哥": 28,
            "土耳其": 28, "以色列": 26, "黎巴嫩": 27,
        }

        # 各运抵国海运天数
        self.country_ocean_days = {}
        for country in self.all_countries:
            days_info = self._loader.get_country_ocean_days(country)
            if days_info and days_info.get("median", 0) >= 5:
                # 历史数据可靠（中位数>=5天）
                self.country_ocean_days[country] = days_info
            else:
                # 历史数据不可靠，使用地理估算
                geo_days = geo_ocean_days.get(country, 30)
                self.country_ocean_days[country] = {
                    "mean": float(geo_days),
                    "median": float(geo_days),
                    "min": geo_days - 3,
                    "max": geo_days + 5,
                    "count": 0,
                    "source": "geographic_estimate",
                }

        # 货好到离港的平均天数
        if '_cr_to_etd_days' in df.columns:
            valid = df['_cr_to_etd_days'].dropna()
            valid = valid[(valid >= 0) & (valid <= 60)]
            self.avg_cr_to_etd_days = {
                "mean": round(float(valid.mean()), 1) if len(valid) else 10.0,
                "median": float(valid.median()) if len(valid) else 10.0,
            }
        else:
            self.avg_cr_to_etd_days = {"mean": 10.0, "median": 10.0}

    # ===== 海运费统计 =====
    def _build_shipping_fee_stats(self):
        """基于海运费收入表构建海运费统计"""
        sf_df = self._loader.shipping_fee
        self.shipping_fee_stats = {}
        for col in ['海运费', '客户海运费', '海运费收入']:
            if col in sf_df.columns:
                vals = sf_df[col].dropna()
                vals = vals[vals > 0]
                if len(vals):
                    self.shipping_fee_stats[col] = {
                        "mean": round(float(vals.mean()), 2),
                        "median": round(float(vals.median()), 2),
                        "min": round(float(vals.min()), 2),
                        "max": round(float(vals.max()), 2),
                        "count": len(vals),
                    }

    # ===== 查询接口 =====
    def get_factory_by_product(self, product_type):
        """根据产品类型获取符合条件的工厂（按产能排序）"""
        result = []
        for name, info in self.factory_info.items():
            products = info.get("products", [])
            
            # 如果没有从物料行匹配到产品，使用产能数据回退
            if not products:
                pvc_cap = info.get("pvc_capacity", 0)
                nitrile_cap = info.get("nitrile_capacity", 0)
                if pvc_cap > 1000:
                    products.append("PVC手套")
                if nitrile_cap > 1000:
                    products.append("丁腈手套")
                # 海外工厂默认支持多种产品
                if info.get("region") == "海外":
                    if "PE产品" not in products:
                        products.append("PE产品")
                    if "小日化产品" not in products:
                        products.append("小日化产品")
            
            if not products:
                continue
                
            matched = False
            for p in products:
                if product_type in p or p in product_type:
                    matched = True
                    break
            if matched:
                result.append({"name": name, "info": info})
                
        # 按产能占比排序
        result.sort(key=lambda x: self._get_product_share(x["info"], product_type), reverse=True)
        return result

    def _get_product_share(self, info, product_type):
        """获取工厂在指定产品上的产能占比"""
        if "PVC" in product_type:
            return info.get("pvc_share", 0)
        elif "丁腈" in product_type:
            return info.get("nitrile_share", 0)
        else:
            return info.get("total_capacity", 0)

    def get_best_dest_port(self, country):
        """获取最优目的港（使用频率最高）"""
        ports = self.country_dest_ports.get(country, [])
        if ports:
            return ports[0]["port"]
        return None

    def get_best_origin_port(self, country, factory_name=None):
        """获取最优始发港"""
        # 优先使用工厂默认港口
        if factory_name and factory_name in self.factory_ports:
            ports = self.factory_ports[factory_name]
            if ports:
                return ports[0]["port"]
        # 其次使用该运抵国最常用始发港
        ports = self.country_origin_ports.get(country, [])
        if ports:
            return ports[0]["port"]
        # 最后使用工厂默认港口
        if factory_name and factory_name in self.factory_info:
            return self.factory_info[factory_name]["default_port"]
        return "青岛/QINGDAO"

    def get_best_trade_term(self, country):
        """获取最优贸易条款（历史最常用）"""
        terms = self.country_trade_terms.get(country, [])
        if terms:
            return terms[0]["term"]
        return "FOB"

    def get_ocean_days(self, country):
        """获取海运天数"""
        info = self.country_ocean_days.get(country)
        if info:
            return info.get("median", 30)
        # 回退到估算值
        return 30

    def get_fee_breakdown(self, country):
        """获取指定运抵国的费用明细"""
        return self.country_fee_stats.get(country, {})

    def get_summary(self):
        """获取知识库摘要（用于LLM上下文）"""
        return {
            "total_factories": len(self.factory_info),
            "total_countries": len(self.all_countries),
            "total_origin_ports": len(self.all_origin_ports),
            "total_fee_categories": len(self.tms_fee_types),
            "avg_shipping_fee": self.shipping_fee_stats.get("海运费", {}).get("median", 2500),
            "avg_cr_to_etd_days": self.avg_cr_to_etd_days.get("median", 10),
            "top_countries": self.all_countries[:10],
            "top_routes": [
                f"{self.country_origin_ports.get(c, [{}])[0].get('port', '?')} → {c}"
                for c in self.all_countries[:5]
            ],
        }

    # ===== 承运商（车队）统计 =====
    def _build_carrier_stats(self):
        """基于集装箱运单构建各工厂的承运商统计"""
        self.factory_carriers = {}
        for factory_name in self.factory_info:
            carriers = self._loader.get_carrier_stats_by_factory(factory_name)
            if carriers:
                self.factory_carriers[factory_name] = carriers

        # 统计自有 vs 外包比例
        self.carrier_type_stats = {}
        all_carriers = []
        for carriers in self.factory_carriers.values():
            all_carriers.extend(carriers)

        type_counts = {"自有": 0, "外包": 0, "客户自提": 0}
        for c in all_carriers:
            t = c.get("type", "外包")
            type_counts[t] = type_counts.get(t, 0) + c["count"]

        total = sum(type_counts.values())
        if total > 0:
            for t, cnt in type_counts.items():
                self.carrier_type_stats[t] = {
                    "count": cnt,
                    "ratio": round(cnt / total * 100, 1),
                }

    def get_best_carrier(self, factory_name):
        """获取指定工厂最常用的承运商（车队）"""
        carriers = self.factory_carriers.get(factory_name, [])
        if carriers:
            return carriers[0]
        return None

    def get_carrier_recommendation(self, factory_name, box_count=0):
        """
        获取承运商推荐方案
        返回: {'recommended': 首选承运商, 'type': 自有/外包, 'alternatives': [...], 'self_owned_ratio': 自有比例}
        """
        carriers = self.factory_carriers.get(factory_name, [])

        if not carriers:
            # 无历史数据时的通用推荐
            return {
                "recommended": "建议从工厂附近物流公司选择",
                "type": "外包",
                "mode": "直拖",
                "alternatives": [],
                "self_owned_ratio": 0,
                "reason": "该工厂暂无历史承运商数据，建议选择港口本地物流公司",
            }

        # 首选：使用频率最高的承运商
        primary = carriers[0]

        # 统计该工厂自有 vs 外包比例
        self_cnt = sum(c["count"] for c in carriers if c["type"] == "自有")
        total_cnt = sum(c["count"] for c in carriers)
        self_ratio = round(self_cnt / total_cnt * 100, 1) if total_cnt > 0 else 0

        # 备选：前3个不同承运商
        alts = carriers[1:4]

        return {
            "recommended": primary["carrier"],
            "type": primary["type"],
            "mode": primary["mode"],
            "count": primary["count"],
            "alternatives": [{"carrier": a["carrier"], "type": a["type"], "count": a["count"]} for a in alts],
            "self_owned_ratio": self_ratio,
        }

    # ===== 船公司知识库 =====
    def _build_shipping_lines(self):
        """构建船公司知识库（基于航线覆盖）"""
        self.shipping_lines = {
            # 中国 → 美国西海岸
            "美国_西海岸": [
                {"name": "Maersk（马士基）", "code": "MSK", "transit_days": 14, "frequency": "每周3班", "advantage": "全球最大，航线最密，时效稳定"},
                {"name": "MSC（地中海航运）", "code": "MSC", "transit_days": 15, "frequency": "每周2班", "advantage": "运力充足，价格有竞争力"},
                {"name": "CMA CGM（达飞）", "code": "CMA", "transit_days": 14, "frequency": "每周2班", "advantage": "法国航线优势，服务好"},
                {"name": "COSCO（中远海运）", "code": "COSCO", "transit_days": 15, "frequency": "每周3班", "advantage": "国内港口优先靠泊"},
                {"name": "ONE（海洋网联）", "code": "ONE", "transit_days": 14, "frequency": "每周2班", "advantage": "日本三大航合并，准班率高"},
            ],
            # 中国 → 美国东海岸
            "美国_东海岸": [
                {"name": "Maersk（马士基）", "code": "MSK", "transit_days": 28, "frequency": "每周2班", "advantage": "东海岸航线覆盖广"},
                {"name": "MSC（地中海航运）", "code": "MSC", "transit_days": 30, "frequency": "每周2班", "advantage": "价格优势明显"},
                {"name": "CMA CGM（达飞）", "code": "CMA", "transit_days": 28, "frequency": "每周1班", "advantage": "经由巴拿马运河，时效快"},
                {"name": "ONE（海洋网联）", "code": "ONE", "transit_days": 29, "frequency": "每周1班", "advantage": "准班率高"},
                {"name": "ZIM（以星航运）", "code": "ZIM", "transit_days": 27, "frequency": "每周1班", "advantage": "东海岸专线，时效最优"},
            ],
            # 中国 → 欧洲
            "欧洲": [
                {"name": "Maersk（马士基）", "code": "MSK", "transit_days": 30, "frequency": "每周3班", "advantage": "欧洲航线市场领导者"},
                {"name": "MSC（地中海航运）", "code": "MSC", "transit_days": 32, "frequency": "每周3班", "advantage": "运力最大，价格有优势"},
                {"name": "CMA CGM（达飞）", "code": "CMA", "transit_days": 30, "frequency": "每周2班", "advantage": "法国总部，欧洲网络最强"},
                {"name": "Hapag-Lloyd（赫伯罗特）", "code": "HPL", "transit_days": 31, "frequency": "每周2班", "advantage": "德国航运公司，北欧优势"},
                {"name": "COSCO（中远海运）", "code": "COSCO", "transit_days": 32, "frequency": "每周2班", "advantage": "国内港口优先，价格稳定"},
            ],
            # 中国 → 东南亚
            "东南亚": [
                {"name": "Maersk（马士基）", "code": "MSK", "transit_days": 7, "frequency": "每周3班", "advantage": "东南亚短线覆盖全"},
                {"name": "CMA CGM（达飞）", "code": "CMA", "transit_days": 7, "frequency": "每周2班", "advantage": "东南亚服务好"},
                {"name": "COSCO（中远海运）", "code": "COSCO", "transit_days": 6, "frequency": "每周3班", "advantage": "国内最近港口出发"},
                {"name": "SITC（海丰国际）", "code": "SITC", "transit_days": 6, "frequency": "每周2班", "advantage": "亚洲区域专线，价格优"},
                {"name": "Wan Hai（万海航运）", "code": "WHL", "transit_days": 7, "frequency": "每周2班", "advantage": "东南亚航线专家"},
            ],
            # 中国 → 中东
            "中东": [
                {"name": "Maersk（马士基）", "code": "MSK", "transit_days": 20, "frequency": "每周2班", "advantage": "中东航线覆盖广"},
                {"name": "MSC（地中海航运）", "code": "MSC", "transit_days": 22, "frequency": "每周1班", "advantage": "价格有竞争力"},
                {"name": "CMA CGM（达飞）", "code": "CMA", "transit_days": 20, "frequency": "每周1班", "advantage": "中东服务网络好"},
                {"name": "EMC（长荣海运）", "code": "EMC", "transit_days": 21, "frequency": "每周1班", "advantage": "中东专线"},
            ],
            # 中国 → 澳洲
            "澳洲": [
                {"name": "Maersk（马士基）", "code": "MSK", "transit_days": 22, "frequency": "每周2班", "advantage": "澳洲航线领先"},
                {"name": "MSC（地中海航运）", "code": "MSC", "transit_days": 24, "frequency": "每周1班", "advantage": "价格有优势"},
                {"name": "CMA CGM（达飞）", "code": "CMA", "transit_days": 22, "frequency": "每周1班", "advantage": "澳洲服务稳定"},
                {"name": "ANL（澳亚航运）", "code": "ANL", "transit_days": 23, "frequency": "每周1班", "advantage": "澳洲本土航运"},
            ],
            # 中国 → 南美
            "南美": [
                {"name": "Maersk（马士基）", "code": "MSK", "transit_days": 38, "frequency": "每周1班", "advantage": "南美航线覆盖广"},
                {"name": "MSC（地中海航运）", "code": "MSC", "transit_days": 40, "frequency": "每周1班", "advantage": "运力充足"},
                {"name": "CMA CGM（达飞）", "code": "CMA", "transit_days": 38, "frequency": "每周1班", "advantage": "南美东海岸优势"},
                {"name": "Hapag-Lloyd（赫伯罗特）", "code": "HPL", "transit_days": 39, "frequency": "每周1班", "advantage": "南美西海岸优势"},
            ],
            # 中国 → 非洲
            "非洲": [
                {"name": "Maersk（马士基）", "code": "MSK", "transit_days": 30, "frequency": "每周1班", "advantage": "非洲航线最全"},
                {"name": "MSC（地中海航运）", "code": "MSC", "transit_days": 32, "frequency": "每周1班", "advantage": "非洲运力最大"},
                {"name": "CMA CGM（达飞）", "code": "CMA", "transit_days": 28, "frequency": "每周1班", "advantage": "北非西非均有覆盖"},
            ],
        }

        # 运抵国 → 区域映射
        self.country_to_region = {
            "美国": "美国_西海岸", "加拿大": "美国_西海岸", "墨西哥": "美国_东海岸",
            "德国": "欧洲", "荷兰": "欧洲", "英国": "欧洲", "法国": "欧洲",
            "意大利": "欧洲", "西班牙": "欧洲", "比利时": "欧洲", "波兰": "欧洲",
            "瑞典": "欧洲", "芬兰": "欧洲", "丹麦": "欧洲", "奥地利": "欧洲",
            "爱尔兰": "欧洲", "葡萄牙": "欧洲", "希腊": "欧洲", "捷克": "欧洲",
            "挪威": "欧洲", "瑞士": "欧洲",
            "日本": "东南亚", "韩国": "东南亚", "新加坡": "东南亚", "泰国": "东南亚",
            "越南": "东南亚", "马来西亚": "东南亚", "菲律宾": "东南亚",
            "印度尼西亚": "东南亚", "文莱": "东南亚",
            "阿联酋": "中东", "沙特阿拉伯": "中东", "阿曼": "中东", "巴林": "中东",
            "科威特": "中东", "约旦": "中东",
            "澳大利亚": "澳洲", "新西兰": "澳洲",
            "巴西": "南美", "阿根廷": "南美", "智利": "南美", "秘鲁": "南美", "哥伦比亚": "南美",
            "南非": "非洲", "埃及": "非洲", "肯尼亚": "非洲", "尼日利亚": "非洲", "摩洛哥": "非洲",
        }

    def get_shipping_lines(self, country):
        """获取指定运抵国的推荐船公司列表"""
        region = self.country_to_region.get(country, "欧洲")
        lines = self.shipping_lines.get(region, self.shipping_lines.get("欧洲", []))

        # 根据目的港进一步细化
        dest_ports = self.country_dest_ports.get(country, [])
        dest_port_name = dest_ports[0]["port"] if dest_ports else ""

        # 按时效排序
        sorted_lines = sorted(lines, key=lambda x: x["transit_days"])
        return {
            "region": region,
            "dest_port": dest_port_name,
            "lines": sorted_lines,
        }

    def get_best_shipping_line(self, country):
        """获取最优船公司（时效最快）"""
        info = self.get_shipping_lines(country)
        if info["lines"]:
            return info["lines"][0]
        return None

    def get_cheapest_shipping_line(self, country, max_transit_days=None):
        """
        获取最便宜的船公司（在满足时效要求的船公司中选最优价格）

        策略：
        1. 如果提供 max_transit_days，只保留 transit_days <= max_transit_days 的船公司
        2. 在符合条件的船公司中，优先选 advantage 字段含"价格"关键字的
        3. 如果多个含价格优势，选 transit_days 最短的（时效越短通常越便宜）
        4. 如果都不含价格优势，选 transit_days 最短的（时效=成本代理指标）

        :param country: 运抵国
        :param max_transit_days: 最大可接受转运天数（None=不限）
        :return: dict with 'recommended', 'available', 'region', 'filtered_count', 'total_count'
        """
        info = self.get_shipping_lines(country)
        all_lines = info["lines"] if info else []
        region = info["region"] if info else "未知"

        if not all_lines:
            return {
                "recommended": None,
                "available": [],
                "region": region,
                "filtered_count": 0,
                "total_count": 0,
            }

        total_count = len(all_lines)

        # 1. 按时效过滤
        if max_transit_days is not None:
            feasible = [l for l in all_lines if l["transit_days"] <= max_transit_days]
            # 如果全部超时，放宽到所有船公司中选最快的（紧急情况）
            if not feasible:
                feasible = [min(all_lines, key=lambda x: x["transit_days"])]
        else:
            feasible = all_lines

        filtered_count = len(feasible)

        # 2. 在符合条件的船公司中，按价格优先级排序
        def price_score(line):
            adv = line.get("advantage", "")
            # 含"价格"关键字 → 高优先级
            if "价格" in adv:
                return (0, line["transit_days"])
            # 含"优势"、"优" → 中优先级
            if "优势" in adv or "优" in adv:
                return (1, line["transit_days"])
            # 其他 → 默认优先级，按 transit_days
            return (2, line["transit_days"])

        sorted_by_price = sorted(feasible, key=price_score)

        return {
            "recommended": sorted_by_price[0],
            "available": sorted_by_price,
            "region": region,
            "filtered_count": filtered_count,
            "total_count": total_count,
            "selection_mode": "cheapest_feasible" if max_transit_days else "cheapest_overall",
        }
