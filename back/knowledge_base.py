"""
知识库 — 基于基础数据 + 配置默认值构建的物流知识库
包含：工厂产能、港口映射（基于配置）、贸易条款、箱型信息、船公司知识、海运天数（地理估算）
"""
import os
import numpy as np
import pandas as pd
from data_loader import DataLoader
import config
from config import FACTORY_SHORT, FACTORY_REGION, NORTH_AMERICA, FDA_COUNTRIES, BOX_TYPE_VOLUME


class KnowledgeBase:
    """物流知识库（基于基础数据 + 配置默认值）"""

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
        self._build_trade_terms()
        self._build_box_types()
        self._build_timeline_stats()
        self._build_shipping_lines()
        self._built = True

    # ===== 工厂信息 =====
    def _build_factory_info(self):
        """基于《工厂分配区间规则》构建工厂信息"""
        rule_df = getattr(self._loader, "allocation_rules", None)
        self.factory_capacity = {}
        self.factory_info = {}
        if rule_df is None or rule_df.empty:
            return

        factory_names = set()
        for col in ("首选工厂", "备选工厂1", "备选工厂2"):
            if col not in rule_df.columns:
                continue
            for val in rule_df[col].dropna():
                name = str(val).strip()
                if name and name != "nan":
                    factory_names.add(name)

        products_by_factory = {name: set() for name in factory_names}
        for _, row in rule_df.iterrows():
            category = str(row.get("物料大类", "") or "")
            if "PVC" in category:
                product = "PVC手套"
            elif "丁腈" in category:
                product = "丁腈手套"
            elif "PE" in category:
                product = "PE产品"
            elif "乳胶" in category:
                product = "乳胶手套"
            else:
                continue
            for col in ("首选工厂", "备选工厂1", "备选工厂2"):
                name = str(row.get(col, "") or "")
                if name and name in products_by_factory:
                    products_by_factory[name].add(product)

        for name in sorted(factory_names):
            region = FACTORY_REGION.get(name, {"region": "国内", "province": "未知", "default_port": "青岛/QINGDAO"})
            short = FACTORY_SHORT.get(name, name)
            self.factory_info[name] = {
                "full_name": name,
                "short_name": short,
                "region": region["region"],
                "province": region["province"],
                "default_port": region["default_port"],
                "pvc_capacity": 0.0,
                "nitrile_capacity": 0.0,
                "pvc_share": 0.0,
                "nitrile_share": 0.0,
                "total_capacity": 0.0,
                "products": sorted(products_by_factory.get(name, [])),
            }
            self.factory_capacity[name] = {
                "pvc_capacity": 0.0,
                "nitrile_capacity": 0.0,
                "total_capacity": 0.0,
                "pvc_share": 0.0,
                "nitrile_share": 0.0,
            }

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

    # ===== 港口与路线（基于港口发货明细推导 + 配置回退） =====
    def _build_port_routes(self):
        """根据《港口发货明细》推导工厂始发港，缺失用配置默认港补齐"""
        self.factory_ports = {}
        detail = getattr(self._loader, "allocation_port_detail", None)
        if detail is not None and not detail.empty and '始发港' in detail.columns and '发货工厂' in detail.columns:
            count_col = '提单单数' if '提单单数' in detail.columns else ('费用记录数' if '费用记录数' in detail.columns else None)
            for factory, grp in detail.groupby('发货工厂'):
                if count_col and count_col in grp.columns:
                    grp = grp.sort_values(count_col, ascending=False)
                ports = []
                for _, row in grp.iterrows():
                    try:
                        count = int(float(row.get(count_col, 0) or 0)) if count_col else 0
                    except (TypeError, ValueError):
                        count = 0
                    ports.append({"port": str(row['始发港']).strip(), "count": count})
                self.factory_ports[str(factory).strip()] = ports
            print(f"[知识库] 从港口发货明细推导 {len(self.factory_ports)} 个工厂的始发港")

        # 对数据中未覆盖的工厂，用 config FACTORY_REGION 的 default_port 补充
        for factory, info in self.factory_info.items():
            if factory not in self.factory_ports or not self.factory_ports[factory]:
                default_port = info.get("default_port", "青岛/QINGDAO")
                if default_port:
                    self.factory_ports[factory] = [{"port": default_port, "count": 0}]

        # 运抵国 -> 目的港映射（来自 运抵国与目的港.xlsx，按运单数降序）
        self.country_dest_ports = {}
        self.country_origin_ports = {}
        self.country_trade_terms = {}
        self.all_countries = []
        self.all_origin_ports = []
        fpath = config.COUNTRY_DEST_PORT_FILE
        if os.path.exists(fpath):
            try:
                df = pd.read_excel(fpath, sheet_name=0)
                for country, grp in df.groupby("运抵国"):
                    rows = grp.sort_values("运单数", ascending=False)
                    ports = []
                    for _, r in rows.iterrows():
                        try:
                            cnt = int(float(r.get("运单数", 0) or 0))
                        except (TypeError, ValueError):
                            cnt = 0
                        ports.append({"port": str(r["目的港"]).strip(), "count": cnt})
                    self.country_dest_ports[str(country).strip()] = ports
                self.all_countries = sorted(self.country_dest_ports.keys())
                print(f"[知识库] 运抵国与目的港: {len(self.all_countries)} 个国家")
            except Exception as e:
                print(f"[知识库] 运抵国与目的港加载失败: {e}")

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
        self.box_type_stats = {}
        self.container_transport_modes = {}

    # ===== 时间统计（地理估算） =====
    def _build_timeline_stats(self):
        """基于地理估算构建运输时间统计"""
        # 地理估算海运天数
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

        # 各运抵国海运天数（全用地理估算）
        self.country_ocean_days = {}
        for country in self.all_countries:
            geo_days = geo_ocean_days.get(country, 30)
            self.country_ocean_days[country] = {
                "mean": float(geo_days),
                "median": float(geo_days),
                "min": geo_days - 3,
                "max": geo_days + 5,
                "count": 0,
                "source": "geographic_estimate",
            }

        # 货好到离港平均天数（默认值）
        self.avg_cr_to_etd_days = {"mean": 10.0, "median": 10.0}

    # ===== 查询接口 =====
    def get_factory_by_product(self, product_type):
        """根据产品类型获取符合条件的工厂（按产能排序）"""
        result = []
        for name, info in self.factory_info.items():
            products = info.get("products", [])

            if not products:
                pvc_cap = info.get("pvc_capacity", 0)
                nitrile_cap = info.get("nitrile_capacity", 0)
                if pvc_cap > 1000:
                    products.append("PVC手套")
                if nitrile_cap > 1000:
                    products.append("丁腈手套")
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
        """获取最优目的港（无历史数据，返回 None 由前端查询）"""
        ports = self.country_dest_ports.get(country, [])
        if ports:
            return ports[0]["port"]
        return None

    def get_best_origin_port(self, country, factory_name=None):
        """获取最优始发港（基于工厂配置的默认港口）"""
        if factory_name and factory_name in self.factory_ports:
            ports = self.factory_ports[factory_name]
            if ports:
                return ports[0]["port"]
        if factory_name and factory_name in self.factory_info:
            return self.factory_info[factory_name]["default_port"]
        return "青岛/QINGDAO"

    def get_best_trade_term(self, country):
        """获取最优贸易条款（默认 FOB）"""
        terms = self.country_trade_terms.get(country, [])
        if terms:
            return terms[0]["term"]
        return "FOB"

    def get_ocean_days(self, country):
        """获取海运天数（优先使用船公司航程数据，回退到地理估算）"""
        # 1. 如果该国有明确的区域映射，从船公司数据获取中位数航程
        if country in self.country_to_region:
            region = self.country_to_region[country]
            lines = self.shipping_lines.get(region, [])
            if lines:
                transit_days_list = [l["transit_days"] for l in lines]
                if transit_days_list:
                    median_days = sorted(transit_days_list)[len(transit_days_list) // 2]
                    return float(median_days)
        # 2. 回退到地理估算（更保守但覆盖更全）
        info = self.country_ocean_days.get(country)
        if info:
            return info.get("median", 30)
        return 30

    def get_fee_breakdown(self, country):
        """获取指定运抵国的费用明细（无历史数据）"""
        return {}

    def get_summary(self):
        """获取知识库摘要（用于LLM上下文）"""
        return {
            "total_factories": len(self.factory_info),
            "total_countries": len(self.all_countries),
            "total_origin_ports": len(self.all_origin_ports),
            "total_fee_categories": 0,
            "avg_shipping_fee": 2500,
            "avg_cr_to_etd_days": self.avg_cr_to_etd_days.get("median", 10),
            "top_countries": self.all_countries[:10],
            "top_routes": [],
        }

    # ===== 承运商（车队）推荐（无历史数据） =====
    def get_carrier_recommendation(self, factory_name, box_count=0):
        """获取承运商推荐方案（无历史数据，返回通用推荐）"""
        return {
            "recommended": "建议从工厂附近物流公司选择",
            "type": "外包",
            "mode": "直拖",
            "alternatives": [],
            "self_owned_ratio": 0,
            "reason": "该工厂暂无历史承运商数据，建议选择港口本地物流公司",
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
            "印度尼西亚": "东南亚", "文莱": "东南亚", "缅甸": "东南亚",
            "阿联酋": "中东", "沙特阿拉伯": "中东", "阿曼": "中东", "巴林": "中东",
            "科威特": "中东", "约旦": "中东",
            "土耳其": "中东", "以色列": "中东", "黎巴嫩": "中东",
            "印度": "中东", "巴基斯坦": "中东", "孟加拉": "中东",
            "澳大利亚": "澳洲", "新西兰": "澳洲",
            "巴西": "南美", "阿根廷": "南美", "智利": "南美", "秘鲁": "南美", "哥伦比亚": "南美",
            "南非": "非洲", "埃及": "非洲", "肯尼亚": "非洲", "尼日利亚": "非洲", "摩洛哥": "非洲",
        }

    def get_shipping_lines(self, country):
        """获取指定运抵国的推荐船公司列表"""
        region = self.country_to_region.get(country, "欧洲")
        lines = self.shipping_lines.get(region, self.shipping_lines.get("欧洲", []))

        dest_ports = self.country_dest_ports.get(country, [])
        dest_port_name = dest_ports[0]["port"] if dest_ports else ""

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
        """获取最便宜的船公司（在满足时效要求的船公司中选最优价格）"""
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

        if max_transit_days is not None:
            feasible = [l for l in all_lines if l["transit_days"] <= max_transit_days]
            if not feasible:
                feasible = [min(all_lines, key=lambda x: x["transit_days"])]
        else:
            feasible = all_lines

        filtered_count = len(feasible)

        def price_score(line):
            adv = line.get("advantage", "")
            if "价格" in adv:
                return (0, line["transit_days"])
            if "优势" in adv or "优" in adv:
                return (1, line["transit_days"])
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
