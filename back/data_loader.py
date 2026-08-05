"""
数据加载器 — 加载并预处理7张Excel数据表
核心数据源：提单运单.xlsx（替代原出口销售订单）
辅助数据：物料行、集装箱运单、费用明细等
"""
import pandas as pd
import numpy as np
import re
from config import FILES, USD_TO_CNY


def _read_first_sheet(fpath):
    """读取Excel文件的第一个有效数据sheet（跳过Query sheet）"""
    try:
        all_sheets = pd.read_excel(fpath, sheet_name=None)
        for name, df in all_sheets.items():
            if df.shape[0] > 0 and df.shape[1] > 1:
                return df
    except Exception as e:
        print(f"[数据加载] 读取 {fpath} 失败: {e}")
    return pd.DataFrame()


def parse_fee_string(fee_str):
    """
    解析费用文本字符串，如：
    'VGM费（AP）: 5.000000 CNY；港杂费（AP）: 3288.000000 CNY'
    返回: [{'name': 'VGM费', 'amount': 5.0, 'currency': 'CNY'}, ...]
    """
    if pd.isna(fee_str) or str(fee_str).strip() == '':
        return []
    fees = []
    parts = str(fee_str).split('；')
    for part in parts:
        match = re.match(r'(.+?)[（(]AP[）)]\s*[:：]\s*([-\d.]+)\s*(\w+)', part.strip())
        if match:
            fees.append({
                'name': match.group(1).strip(),
                'amount': float(match.group(2)),
                'currency': match.group(3).strip(),
            })
    return fees


def _try_parse_date_columns(df, columns):
    """尝试解析日期列，忽略不存在的列"""
    for col in columns:
        if col in df.columns:
            df[col] = pd.to_datetime(df[col], errors='coerce')


class DataLoader:
    """加载并缓存所有数据表"""

    _instance = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._loaded = False
        return cls._instance

    def load_all(self):
        """加载所有数据表"""
        if self._loaded:
            return
        print("[数据加载] 正在加载各基地产能...")
        self.factory_capacity = self._load_factory_capacity()
        
        print("[数据加载] 正在加载海运费收入...")
        self.shipping_fee = self._load_shipping_fee()
        
        print("[数据加载] 正在加载费用明细...")
        self.costs = self._load_costs()
        
        print("[数据加载] 正在加载集装箱运单...")
        self.container_waybill = self._load_container_waybill()
        
        print("[数据加载] 正在加载物料行...")
        self.material_line = self._load_material_line()
        
        print("[数据加载] 正在加载提单运单（核心数据源）...")
        self.bl_waybill = self._load_bl_waybill()
        
        print("[数据加载] 正在加载TMS费用类型...")
        self.tms_fee_type = self._load_tms_fee_type()
        
        # 构建衍生字段
        self._build_derived_fields()
        
        print(f"[数据加载] 完成，核心数据源 {len(self.bl_waybill)} 条记录")
        self._loaded = True

    def _build_derived_fields(self):
        """在 bl_waybill 上构建衍生字段（海运天数、费用等）"""
        df = self.bl_waybill
        if df.empty:
            return

        # 计算海运天数
        if '预计离港时间' in df.columns and '预计到港时间' in df.columns:
            df['_ocean_days'] = (df['预计到港时间'] - df['预计离港时间']).dt.days
        elif '实际离港时间' in df.columns and '实际到港时间' in df.columns:
            df['_ocean_days'] = (df['实际到港时间'] - df['实际离港时间']).dt.days

        # 计算货好到离港天数
        if '预计货好时间' in df.columns and '预计离港时间' in df.columns:
            df['_cr_to_etd_days'] = (df['预计离港时间'] - df['预计货好时间']).dt.days
        elif '实际货好时间' in df.columns and '实际离港时间' in df.columns:
            df['_cr_to_etd_days'] = (df['实际离港时间'] - df['实际货好时间']).dt.days

        # 解析费用字段（如果存在）
        for fee_col in ['提单费用', '集装箱费用', '费用明细']:
            if fee_col in df.columns:
                parsed_col = f'_parsed_{fee_col}'
                df[parsed_col] = df[fee_col].apply(parse_fee_string)

        # 计算总费用
        parsed_cols = [c for c in df.columns if c.startswith('_parsed_') and c.endswith('_fees')]
        if parsed_cols:
            df['_total_fee_cny'] = df.apply(lambda row: self._calc_row_fee(row, parsed_cols), axis=1)

        # 添加占位列以兼容下游代码
        for col in ['箱型', '箱数', '重量', '体积', '集装箱运输方式']:
            if col not in df.columns:
                df[col] = np.nan

    def _calc_row_fee(self, row, parsed_cols):
        """计算一行的总费用"""
        total = 0.0
        for col in parsed_cols:
            fees = row.get(col, [])
            if fees and isinstance(fees, list):
                for f in fees:
                    if isinstance(f, dict):
                        if f.get('currency') == 'CNY':
                            total += f.get('amount', 0)
                        elif f.get('currency') == 'USD':
                            total += f.get('amount', 0) * USD_TO_CNY
        return total

    # ===== 数据加载方法 =====
    def _load_factory_capacity(self):
        df = _read_first_sheet(FILES["factory_capacity"])
        print(f"  各基地产能: {len(df)} 行, 列: {list(df.columns)}")
        return df

    def _load_shipping_fee(self):
        df = _read_first_sheet(FILES["shipping_fee"])
        for col in ['海运费', '客户海运费', '海运费收入']:
            if col in df.columns:
                df[col] = pd.to_numeric(df[col], errors='coerce')
        print(f"  海运费收入: {len(df)} 行")
        return df

    def _load_costs(self):
        df = _read_first_sheet(FILES["costs"])
        if '含税金额' in df.columns:
            df['含税金额'] = pd.to_numeric(df['含税金额'], errors='coerce')
        if '不含税金额' in df.columns:
            df['不含税金额'] = pd.to_numeric(df['不含税金额'], errors='coerce')
        print(f"  费用明细: {len(df)} 行")
        return df

    def _load_container_waybill(self):
        df = _read_first_sheet(FILES["container_waybill"])
        if '装柜日期' in df.columns:
            df['装柜日期'] = pd.to_datetime(df['装柜日期'], errors='coerce')
        print(f"  集装箱运单: {len(df)} 行")
        return df

    def _load_material_line(self):
        df = _read_first_sheet(FILES["material_line"])
        print(f"  物料行: {len(df)} 行")
        return df

    def _load_bl_waybill(self):
        df = _read_first_sheet(FILES["bl_waybill"])
        # 尝试解析所有可能的日期列
        date_cols = ['预计货好时间', '预计船期', '预计离港时间', '实际离港时间', 
                     '预计到港时间', '实际到港时间', '实际货好时间', '出货日期']
        _try_parse_date_columns(df, date_cols)
        print(f"  提单运单: {len(df)} 行, 列: {list(df.columns)}")
        return df

    def _load_tms_fee_type(self):
        df = _read_first_sheet(FILES["tms_fee_type"])
        print(f"  TMS费用类型: {len(df)} 行")
        return df

    # ===== 查询接口 =====
    def get_country_dest_ports(self, country):
        """获取指定运抵国的所有目的港（按使用频率排序）"""
        df = self.bl_waybill
        col = '目的港'
        if col not in df.columns:
            return []
        subset = df[df['运抵国'] == country] if '运抵国' in df.columns else pd.DataFrame()
        if subset.empty:
            return []
        ports = subset[col].dropna().value_counts()
        return [{"port": idx, "count": int(cnt)} for idx, cnt in ports.items()]

    def get_country_origin_ports(self, country):
        """获取指定运抵国最常用的始发港"""
        df = self.bl_waybill
        col = '始发港'
        if col not in df.columns:
            return []
        subset = df[df['运抵国'] == country] if '运抵国' in df.columns else pd.DataFrame()
        if subset.empty:
            return []
        ports = subset[col].dropna().value_counts()
        return [{"port": idx, "count": int(cnt)} for idx, cnt in ports.items()]

    def get_country_trade_terms(self, country):
        """获取指定运抵国最常用的贸易条款"""
        df = self.bl_waybill
        col = '贸易条款'
        if col not in df.columns:
            return []
        subset = df[df['运抵国'] == country] if '运抵国' in df.columns else pd.DataFrame()
        if subset.empty:
            return []
        terms = subset[col].dropna().value_counts()
        return [{"term": idx, "count": int(cnt)} for idx, cnt in terms.items()]

    def get_country_ocean_days(self, country):
        """获取指定运抵国的海运天数统计"""
        df = self.bl_waybill
        if '_ocean_days' not in df.columns:
            return None
        subset = df[(df['运抵国'] == country) & df['_ocean_days'].notna() & (df['_ocean_days'] > 0)]
        if subset.empty:
            return None
        days = subset['_ocean_days']
        return {
            "mean": round(float(days.mean()), 1),
            "median": float(days.median()),
            "min": int(days.min()),
            "max": int(days.max()),
            "count": len(days)
        }

    def get_country_avg_cost(self, country):
        """获取指定运抵国的平均总费用"""
        df = self.bl_waybill
        if '_total_fee_cny' not in df.columns:
            return None
        subset = df[(df['运抵国'] == country) & (df['_total_fee_cny'] > 0)]
        if subset.empty:
            return None
        return {
            "mean": round(float(subset['_total_fee_cny'].mean()), 2),
            "median": round(float(subset['_total_fee_cny'].median()), 2),
            "count": len(subset)
        }

    def get_factory_routes(self, factory_name):
        """获取指定工厂的历史发货记录"""
        df = self.bl_waybill
        col = '发货工厂'
        if col not in df.columns:
            return pd.DataFrame()
        subset = df[df[col].astype(str).str.contains(factory_name, na=False)]
        return subset

    def get_fee_stats_by_country(self, country):
        """获取指定运抵国的费用明细统计（从提单运单+费用表获取）"""
        df = self.bl_waybill
        if '运抵国' not in df.columns:
            return {}

        subset = df[df['运抵国'] == country]
        if subset.empty:
            return {}

        stats = {}

        # 收集所有解析的费用字段
        parsed_cols = [c for c in df.columns if c.startswith('_parsed_')]
        for col in parsed_cols:
            fees_list = []
            for fees in subset[col]:
                if fees and isinstance(fees, list):
                    fees_list.extend(fees)

            for f in fees_list:
                if isinstance(f, dict):
                    key = f.get('name', '未知费用')
                    if key not in stats:
                        stats[key] = []
                    amount = f.get('amount', 0)
                    if f.get('currency') == 'USD':
                        amount *= USD_TO_CNY
                    if amount > 0:
                        stats[key].append(amount)

        result = {}
        for name, amounts in stats.items():
            arr = np.array(amounts)
            if len(arr) > 0:
                result[name] = {
                    "count": len(arr),
                    "mean": round(float(np.mean(arr)), 2),
                    "median": round(float(np.median(arr)), 2),
                    "min": round(float(np.min(arr)), 2),
                    "max": round(float(np.max(arr)), 2),
                }

        # 如果没有从提单解析到费用，从费用明细表回退
        if not result and not self.costs.empty:
            result = self._get_fee_stats_from_costs_table(country)

        return result

    def _get_fee_stats_from_costs_table(self, country):
        """从费用明细表获取费用统计（回退方案）"""
        result = {}
        df = self.costs
        if '费用大类' not in df.columns or '含税金额' not in df.columns:
            return result

        # 按费用大类统计
        for fee_class, group in df.groupby('费用大类'):
            amounts = group['含税金额'].dropna()
            amounts = amounts[(amounts > 0) & (amounts < 500000)]  # 排除异常值
            if len(amounts) >= 5:
                arr = np.array(amounts)
                result[fee_class] = {
                    "count": len(arr),
                    "mean": round(float(np.mean(arr)), 2),
                    "median": round(float(np.median(arr)), 2),
                    "min": round(float(np.min(arr)), 2),
                    "max": round(float(np.max(arr)), 2),
                }

        return result

    def get_box_type_stats(self):
        """获取集装箱箱型统计"""
        df = self.bl_waybill
        # 优先使用集装箱运单数据
        if not self.container_waybill.empty and '箱型' in self.container_waybill.columns:
            cw = self.container_waybill
            stats = cw.groupby('箱型').agg(
                count=('箱数', 'count') if '箱数' in cw.columns else ('箱型', 'count'),
            ).to_dict('index')
            return stats

        # 回退：使用提单运单
        if '箱型' in df.columns:
            stats = df.groupby('箱型').agg(count=('箱型', 'count')).to_dict('index')
            return stats

        return {}

    def get_container_transport_mode_stats(self):
        """获取集装箱运输方式统计"""
        df = self.bl_waybill
        col = '集装箱运输方式'
        if col in df.columns:
            return df[col].value_counts().to_dict()
        return {}

    def get_carrier_stats_by_factory(self, factory_name):
        """
        获取指定工厂的承运商统计（从集装箱运单）
        返回: [{'carrier': '承运商名称', 'count': 次数, 'mode': '运输方式', 'type': '自有/外包'}, ...]
        """
        cw = self.container_waybill
        if cw.empty or '承运商' not in cw.columns:
            return []

        # 通过提单运单id关联工厂
        bl = self.bl_waybill
        if bl.empty or '发货工厂' not in bl.columns or '提单运单id' not in bl.columns:
            return []

        # 找到该工厂的提单运单id
        factory_bls = bl[bl['发货工厂'].astype(str).str.contains(factory_name, na=False)]
        if factory_bls.empty:
            return []

        bl_ids = set(factory_bls['提单运单id'].dropna().tolist())

        # 关联集装箱运单
        if '提单运单id' not in cw.columns:
            return []

        subset = cw[cw['提单运单id'].isin(bl_ids)]
        if subset.empty:
            return []

        results = []
        for carrier, group in subset.groupby('承运商'):
            if pd.isna(carrier) or str(carrier).strip() == '':
                continue
            mode = group['运输方式'].mode()
            mode_str = str(mode.iloc[0]) if len(mode) > 0 else '未知'
            carrier_type = self._classify_carrier_type(str(carrier), mode_str)
            results.append({
                'carrier': str(carrier),
                'count': len(group),
                'mode': mode_str,
                'type': carrier_type,
            })

        results.sort(key=lambda x: x['count'], reverse=True)
        return results

    def _classify_carrier_type(self, carrier_name, transport_mode):
        """
        根据运输方式和承运商名称判断是自有车队还是外包
        工厂自运/工厂自运-甩挂 = 自有车队
        其他 = 外包车队
        """
        self_owned_modes = ['工厂自运', '工厂自运-甩挂']
        if any(m in transport_mode for m in self_owned_modes):
            return '自有'
        if '自提' in transport_mode:
            return '客户自提'
        return '外包'
