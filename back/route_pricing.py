"""
工厂到起运港拖车费数据查询 — 共享模块
供 app.py 路由 和 cost_calculator.py 共同使用
"""
import os
import re
import time
import pandas as pd

DATA_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'data')
ROUTE_PRICING_FILE = os.path.join(DATA_DIR, '工厂到起运港拖车费_运输方式承运商发货工厂始发港.xlsx')
TIME_ANALYSIS_FILE = os.path.join(DATA_DIR, '工厂到起运港时效分析表.xlsx')

_CACHE = None
_CACHE_TIME = None
_CACHE_TTL = 600
_TIME_CACHE = None
_TIME_CACHE_TIME = None


def load_route_pricing():
    """加载工厂到起运港拖车费 Excel（带缓存）"""
    global _CACHE, _CACHE_TIME
    now = time.time()
    if _CACHE is not None and _CACHE_TIME is not None:
        if now - _CACHE_TIME < _CACHE_TTL:
            return _CACHE
    if not os.path.exists(ROUTE_PRICING_FILE):
        return None
    try:
        df = pd.read_excel(ROUTE_PRICING_FILE, sheet_name=0)
        _CACHE = df
        _CACHE_TIME = now
        return df
    except Exception:
        return None


def load_time_analysis():
    """加载工厂到起运港时效分析表（带缓存）"""
    global _TIME_CACHE, _TIME_CACHE_TIME
    now = time.time()
    if _TIME_CACHE is not None and _TIME_CACHE_TIME is not None:
        if now - _TIME_CACHE_TIME < _CACHE_TTL:
            return _TIME_CACHE
    if not os.path.exists(TIME_ANALYSIS_FILE):
        return None
    try:
        df = pd.read_excel(TIME_ANALYSIS_FILE, sheet_name=0)
        _TIME_CACHE = df
        _TIME_CACHE_TIME = now
        return df
    except Exception:
        return None


def query_land_transit_time(factory, origin_port, transport_mode='direct'):
    """
    从时效分析表查询工厂到起运港的建议标准时效

    返回:
        dict with days, median_days, sample_count, source
        或 None（无匹配数据）
    """
    df = load_time_analysis()
    if df is None or df.empty:
        return None

    mode_cn = TRANSPORT_MODE_CN.get(transport_mode, transport_mode)
    factory_mask = df['发货工厂'].apply(lambda x: match_factory(x, factory))
    port_mask = df['起运港'].apply(lambda x: match_port(x, origin_port))
    mode_mask = df['运输方式'].str.strip() == mode_cn

    matched = df[factory_mask & port_mask & mode_mask].copy()

    if matched.empty:
        return None

    col_recommended = '建议标准时效(天)'
    col_median = '中位数(天)'
    col_samples = '样本数'
    best = matched.sort_values(col_samples, ascending=False).iloc[0]

    days = float(best[col_recommended]) if pd.notna(best.get(col_recommended)) else None
    if days is None or days <= 0:
        days = float(best[col_median]) if pd.notna(best.get(col_median)) else None

    if days is None or days <= 0:
        return None

    return {
        'days': round(days, 1),
        'median_days': float(best[col_median]) if pd.notna(best.get(col_median)) else round(days, 1),
        'sample_count': int(best[col_samples]) if pd.notna(best.get(col_samples)) else 0,
        'source': 'excel_time_analysis',
    }


def match_factory(excel_val, query_val):
    """工厂名匹配：精确匹配 → 核心名开头匹配"""
    ev = str(excel_val).strip()
    qv = str(query_val).strip()
    if ev == qv:
        return True
    core_match = re.search(r'^(.+?英科)', qv)
    if not core_match:
        core_match = re.search(r'^(英科)', qv)
    if core_match:
        return ev.startswith(core_match.group(1))
    return False


def match_port(excel_val, query_val):
    """港口中文名匹配"""
    ev = str(excel_val).strip()
    qv = str(query_val).strip()
    cn_match = re.match(r'[一-鿿]+', qv)
    if not cn_match:
        cn_match = re.search(r'[一-鿿]+', qv)
    if cn_match:
        return cn_match.group() in ev
    return qv in ev


TRANSPORT_MODE_CN = {
    'direct': '直拖',
    'seaRail': '海铁',
    'factorySelf': '工厂自运',
    'landToWater': '陆改水',
}


def query_land_freight(factory, origin_port, transport_mode='direct', box_type='40HQ', min_samples=3):
    """
    查询陆运费推荐

    参数:
        factory: 工厂全称
        origin_port: 始发港
        transport_mode: 运输方式 (direct/seaRail/factorySelf/landToWater)
        box_type: 箱型
        min_samples: 推荐时最少样本数（过滤离群值）

    返回:
        dict with: recommended_carrier, recommended_fee, total_matched, all_quotes
        或 None（无匹配数据）
    """
    df = load_route_pricing()
    if df is None or df.empty:
        return None

    mode_cn = TRANSPORT_MODE_CN.get(transport_mode, transport_mode)
    bt = str(box_type).strip().upper()

    factory_mask = df['发货工厂'].apply(lambda x: match_factory(x, factory))
    port_mask = df['始发港'].apply(lambda x: match_port(x, origin_port))
    mode_mask = df['运输方式'].str.strip() == mode_cn
    box_mask = df['箱型'].str.strip().str.upper() == bt

    matched = df[factory_mask & port_mask & mode_mask & box_mask].copy()

    if matched.empty:
        matched = df[factory_mask & port_mask & mode_mask].copy()

    if matched.empty:
        return None

    col_land = '陆运费中位数(元)'
    # 优先使用样本数≥min_samples的承运商，再做按运输笔数的加权中位数
    reliable = matched[matched['运输笔数'] >= min_samples]
    pool = reliable.copy() if len(reliable) > 0 else matched.copy()
    pool = pool.dropna(subset=[col_land]).copy()
    pool['运输笔数'] = pd.to_numeric(pool['运输笔数'], errors='coerce').fillna(0)
    if pool.empty:
        return None

    # 用运输笔数做加权中位数，避免个别异常低价承运商拉低整条路线费用
    pool_sorted = pool.sort_values(col_land).copy()
    total_weight = float(pool_sorted['运输笔数'].sum())
    if total_weight <= 0:
        best_idx = pool_sorted[col_land].idxmin()
        best_row = pool_sorted.loc[best_idx]
    else:
        half_weight = total_weight / 2.0
        cum_weight = 0
        best_row = pool_sorted.iloc[0]
        for _, row in pool_sorted.iterrows():
            cum_weight += row['运输笔数']
            best_row = row
            if cum_weight >= half_weight:
                break

    matched_sorted = matched.sort_values(col_land)
    all_quotes = []
    for _, row in matched_sorted.head(20).iterrows():
        all_quotes.append({
            'carrier': str(row.get('公司(收款方)', '')),
            'boxType': str(row.get('箱型', '')),
            'sampleCount': int(row.get('运输笔数', 0)) if pd.notna(row.get('运输笔数')) else 0,
            'landFreightMedian': float(row.get(col_land, 0)) if pd.notna(row.get(col_land)) else 0,
        })

    return {
        'recommended_carrier': str(best_row.get('公司(收款方)', '')),
        'recommended_fee': float(best_row[col_land]),
        'sample_count': int(best_row.get('运输笔数', 0)) if pd.notna(best_row.get('运输笔数')) else 0,
        'total_matched': len(matched),
        'all_quotes': all_quotes,
    }
