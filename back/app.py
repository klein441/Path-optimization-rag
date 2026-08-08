"""
Flask API 服务器 — 物流运输路径智能优化后端（基于8张数据表重新设计）

接口：
  POST /api/logistics/recommend  — 获取推荐方案
  GET  /api/logistics/knowledge  — 获取知识库摘要
  GET  /api/logistics/factories  — 获取工厂列表
  GET  /api/logistics/countries  — 获取所有运抵国列表
  GET  /api/logistics/country-info — 获取指定运抵国详情
  GET  /api/logistics/health     — 健康检查
  GET  /api/freight-rate         — 海运费合约查询（读取合约信息导出0806.xlsx）
  GET  /api/route-info           — 航线信息查询（产品→工厂→港口链路）
"""
import sys
import os
import time
import json as json_module
from datetime import datetime, timedelta
from flask import Flask, request, jsonify
from flask_cors import CORS
import requests

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import config
from recommendation_engine import RecommendationEngine

app = Flask(__name__, static_folder=os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "front"), static_url_path="")
CORS(app, origins=config.CORS_ORIGINS)

# 全局实例
engine = None


@app.route('/')
def index():
    return app.send_static_file('logistics-optimizer.html')


def get_engine():
    global engine
    if engine is None:
        print("[启动] 正在加载8张数据表并构建知识库...")
        engine = RecommendationEngine()
        print("[启动] 知识库构建完成")
    return engine


@app.route('/api/logistics/health', methods=['GET'])
def health_check():
    """健康检查"""
    return jsonify({
        'status': 'ok',
        'service': 'Logistics Route Optimization API v3',
        'engine': 'data_driven_v3',
        'llm_enabled': config.LLM_ENABLED,
        'llm_model': config.LLM_MODEL if config.LLM_ENABLED else None,
        'data_sources': 7,
        'timestamp': datetime.now().isoformat(),
    })


@app.route('/api/logistics/knowledge', methods=['GET'])
def get_knowledge():
    """获取知识库摘要"""
    eng = get_engine()
    summary = eng.get_kb_summary()
    return jsonify({
        'success': True,
        'summary': summary,
        'factories': list(eng.get_factories().keys()),
    })


@app.route('/api/logistics/factories', methods=['GET'])
def get_factories():
    """获取工厂列表及产能信息"""
    eng = get_engine()
    factories = eng.get_factories()
    result = []
    for name, info in factories.items():
        result.append({
            'name': name,
            'shortName': info.get('short_name', name),
            'region': info.get('region', ''),
            'province': info.get('province', ''),
            'defaultPort': info.get('default_port', ''),
            'products': info.get('products', []),
            'pvcCapacity': info.get('pvc_capacity', 0),
            'nitrileCapacity': info.get('nitrile_capacity', 0),
            'pvcShare': info.get('pvc_share', 0),
            'nitrileShare': info.get('nitrile_share', 0),
            'totalCapacity': info.get('total_capacity', 0),
        })
    return jsonify({'success': True, 'factories': result})


@app.route('/api/logistics/countries', methods=['GET'])
def get_countries():
    """获取所有支持的运抵国列表"""
    eng = get_engine()
    countries = eng.get_countries()
    return jsonify({'success': True, 'countries': countries, 'count': len(countries)})


@app.route('/api/logistics/country-info', methods=['GET'])
def get_country_info():
    """获取指定运抵国的详细信息"""
    country = request.args.get('country', '')
    if not country:
        return jsonify({'error': '缺少 country 参数'}), 400

    eng = get_engine()
    info = eng.get_country_info(country)
    return jsonify({'success': True, 'info': info})


@app.route('/api/logistics/recommend', methods=['POST'])
def recommend():
    """核心接口 — 获取物流路径推荐方案

    请求体 JSON:
    {
        "customer": "客户名称",
        "productType": "丁腈手套",
        "destCountry": "美国",
        "boxCount": 800,
        "weight": 12000,
        "volume": 68,
        "cargoReady": "2026-08-15",
        "shipSchedule": "2026-08-20",
        "transportPref": "balanced",
        "tradePref": "auto"
    }
    """
    data = request.get_json()
    if not data:
        return jsonify({'error': '请求体不能为空'}), 400

    # 参数校验
    required = ['productType', 'destCountry', 'boxCount', 'weight', 'volume', 'cargoReady', 'shipSchedule']
    for field in required:
        if field not in data or data[field] in (None, ''):
            return jsonify({'error': f'缺少必填字段: {field}'}), 400

    try:
        eng = get_engine()
        result = eng.recommend(data)

        # 构建前端友好的响应格式
        primary = result.get('primary', {})
        alternatives = result.get('alternatives', [])

        response = {
            'success': True,
            'data': {
                'primary': _format_primary(primary, result),
                'alternatives': [_format_alt(a) for a in alternatives],
                'reasoning': result.get('reasoning', ''),
                'riskWarning': result.get('risk_warning', ''),
                'optimizationSuggestion': result.get('optimization_suggestion', ''),
                'dataStats': result.get('dataStats', {}),
                'source': result.get('source', 'rule_engine'),
                'engine': result.get('engine', 'data_driven_v2'),
                'llmEnabled': result.get('llm_enabled', False),
                'llmModel': result.get('llm_model', ''),
                'eligibleFactoriesCount': result.get('eligibleFactories', 0),
                'dataSources': result.get('data_sources', []),
                'generatedAt': result.get('generatedAt', datetime.now().isoformat()),
            }
        }
        return jsonify(response)

    except Exception as e:
        import traceback
        traceback.print_exc()
        return jsonify({'error': f'推荐生成失败: {str(e)}'}), 500


def _format_primary(p, full_result):
    """格式化主方案为前端友好格式"""
    cost = p.get('cost', {})
    timeline = p.get('timeline', {})
    trade_info = p.get('tradeTermInfo', {})

    return {
        'factory': p.get('factory', ''),
        'factoryShort': p.get('factory_short', ''),
        'region': p.get('region', ''),
        'departurePort': p.get('departurePort', ''),
        'destPort': p.get('destPort', ''),
        'tradeTerm': p.get('tradeTerm', ''),
        'tradeTermInfo': {
            'full': trade_info.get('full', p.get('tradeTerm', '')),
            'desc': trade_info.get('desc', ''),
            'sellerResp': trade_info.get('seller_resp', ''),
            'costScope': trade_info.get('cost_scope', ''),
        },
        'boxType': p.get('boxType', '40HQ'),
        'boxTypes': cost.get('box_types', [p.get('boxType', '40HQ')]),
        'boxTypeCounts': cost.get('box_type_counts', {p.get('boxType', '40HQ'): cost.get('box_count', 1)}),
        'boxCount': cost.get('box_count', 1),
        'score': p.get('score', 0),
        'inlandDays': timeline.get('inland_days', 0),
        'oceanDays': timeline.get('ocean_days', 0),
        'etd': timeline.get('etd', ''),
        'eta': timeline.get('eta', ''),
        'cargoReady': timeline.get('cargo_ready', ''),
        'shipSchedule': timeline.get('ship_schedule', ''),
        'totalDays': timeline.get('total_days', 0),
        'timeline': timeline,
        'cost': {
            'items': cost.get('items', []),
            'totalCny': cost.get('total_cny', 0),
            'totalUsd': cost.get('total_usd', 0),
            'currency': cost.get('currency', 'CNY'),
            'note': cost.get('note', ''),
            'box_count': cost.get('box_count', 1),
            'box_types': cost.get('box_types', [p.get('boxType', '40HQ')]),
            'box_type_counts': cost.get('box_type_counts', {p.get('boxType', '40HQ'): 1}),
            'calc_details': cost.get('calc_details', []),
        },
        'factoryInfo': p.get('factoryInfo', {}),
        'carrier': p.get('carrier', {}),
        'shippingLine': p.get('shippingLine', {}),
        'shippingLines': p.get('shippingLines', {}),
        'isOverseas': p.get('region', '') == '海外',
        'needFDA': p.get('needFDA', False),
    }


def _format_alt(a):
    """格式化备选方案"""
    cost = a.get('cost', {})
    timeline = a.get('timeline', {})
    return {
        'factory': a.get('factory', ''),
        'factoryShort': a.get('factory_short', ''),
        'region': a.get('region', ''),
        'departurePort': a.get('departurePort', ''),
        'destPort': a.get('destPort', ''),
        'tradeTerm': a.get('tradeTerm', ''),
        'boxType': a.get('boxType', '40HQ'),
        'score': a.get('score', 0),
        'inlandDays': timeline.get('inland_days', 0),
        'oceanDays': timeline.get('ocean_days', 0),
        'etd': timeline.get('etd', ''),
        'eta': timeline.get('eta', ''),
        'totalDays': timeline.get('total_days', 0),
        'totalCost': cost.get('total_cny', 0),
        'totalCostCny': cost.get('total_cny', 0),
        'totalCostUsd': cost.get('total_usd', 0),
        'carrier': a.get('carrier', {}),
        'shippingLine': a.get('shippingLine', {}),
        'isOverseas': a.get('region', '') == '海外',
    }


# ===== 航线信息查询（产品→工厂→港口链路）=====

def _clean_port_name(port_name):
    """清理港口名称：去掉 LOCODE 前缀和多余的空格/斜杠"""
    if not port_name:
        return ''
    name = str(port_name).strip()
    # 处理 "CNSHA / 上海/SHANGHAI" 格式 → "上海/SHANGHAI"
    if ' / ' in name:
        parts = name.split(' / ', 1)
        if len(parts) == 2 and len(parts[0]) <= 6:
            name = parts[1]
    # 去掉末尾的州代码后缀如 ",CA"
    import re as _re
    name = _re.sub(r',\s*[A-Z]{2}$', '', name)
    return name.strip()


@app.route('/api/route-info', methods=['GET'])
def get_route_info():
    """
    根据产品类型和运抵国，查询最优航线信息

    参数:
        productType  — 产品类型（丁腈手套/PVC手套/PE产品/轮椅/小日化产品）
        destCountry  — 运抵国
        boxType      — 箱型（可选，默认 40HQ）
        cargoReady   — 货好时间 ISO字符串（可选，用于计算时效约束）
        shipSchedule — 期望船期 ISO字符串（可选，用于计算时效约束）

    返回:
        factory, originPort, originPortCode, destPort, destPortCode,
        boxType, loadType, isFCL, recommendedShippingLine, availableShippingLines,
        transitDays, selectionMode
    """
    from datetime import datetime as dt

    product_type = request.args.get('productType', '')
    dest_country = request.args.get('destCountry', '')
    box_type = request.args.get('boxType', '40HQ')
    cargo_ready = request.args.get('cargoReady', '')
    ship_schedule = request.args.get('shipSchedule', '')

    if not product_type or not dest_country:
        return jsonify({
            'success': False,
            'error': '缺少必填参数: productType, destCountry',
        }), 400

    eng = get_engine()
    kb = eng.kb

    # 1. 根据产品类型找最优工厂（与推荐引擎保持一致的排序逻辑）
    factories = kb.get_factory_by_product(product_type)
    if not factories:
        # 回退：使用所有工厂
        for name, info in kb.factory_info.items():
            factories.append({"name": name, "info": info})

    # 北美市场优先海外工厂（与推荐引擎 _find_factories 保持一致）
    if dest_country in config.NORTH_AMERICA:
        factories.sort(key=lambda x: 0 if x["info"].get("region", "") == "海外" else 1)

    best_factory = factories[0]
    factory_name = best_factory["name"]
    factory_info = best_factory["info"]

    # 2. 根据工厂确定始发港
    origin_port = kb.get_best_origin_port(dest_country, factory_name)

    # 3. 根据运抵国确定目的港
    dest_port = kb.get_best_dest_port(dest_country)
    if not dest_port:
        dest_port = dest_country + " 主港"

    # 清理港口名（去掉可能的州代码后缀如 ",CA"）
    dest_port_clean = _clean_port_name(dest_port)
    origin_port_clean = _clean_port_name(origin_port)

    # 4. 港口代码（从港口名里的 LOCODE 提取，如 "CNSHA / 上海/SHANGHAI" → "CNSHA"）
    def _extract_port_code(port_name):
        import re as _re_local
        if not port_name:
            return ""
        # 如果本身就像 LOCODE（5位字母数字）
        if _re_local.match(r'^[A-Z]{2}[A-Z0-9]{3}$', str(port_name).strip()):
            return str(port_name).strip()
        # 从 "CNSHA / 上海/SHANGHAI" 格式里提取前缀
        m = _re_local.match(r'^([A-Z]{2}[A-Z0-9]{3})\s*/', str(port_name).strip())
        if m:
            return m.group(1)
        return str(port_name).strip()
    origin_code = _extract_port_code(origin_port_clean)
    dest_code = _extract_port_code(dest_port_clean)

    # 5. 箱型 → 合约报价列（用于isFCL判断，整箱都是FCL）
    is_fcl = box_type in ('20GP', '40GP', '40HQ', '45HQ', '20RF', '40RF', '40HC', '45HC')
    load_type = 'FCL' if is_fcl else 'LCL'

    # 6. 计算最大可接受转运天数
    max_transit_days = None
    if cargo_ready and ship_schedule:
        try:
            cr = dt.fromisoformat(cargo_ready)
            ss = dt.fromisoformat(ship_schedule)
            available_days = (ss - cr).days
            if available_days > 0:
                # 预留内陆运输+清关时间（约5天），其余给海运
                max_transit_days = max(available_days - 5, 1)
        except (ValueError, TypeError):
            pass

    # 7. 获取最便宜的船公司（在时效约束内）
    shipping_result = kb.get_cheapest_shipping_line(dest_country, max_transit_days)

    # 8. 获取转运天数（从推荐船公司取，或回退到知识库估算）
    recommended_line = shipping_result.get("recommended")
    transit_days = recommended_line["transit_days"] if recommended_line else kb.get_ocean_days(dest_country)

    return jsonify({
        'success': True,
        'data': {
            'factory': factory_name,
            'factoryShort': factory_info.get('short_name', factory_name),
            'factoryRegion': factory_info.get('region', '国内'),
            'factoryProvince': factory_info.get('province', ''),
            'originPort': origin_port_clean,
            'originPortCode': origin_code,
            'destPort': dest_port_clean,
            'destPortCode': dest_code,
            'boxType': box_type,
            'loadType': load_type,
            'isFCL': is_fcl,
            'cargoType': '普货',  # 默认全部普货
            'transitDays': transit_days,
            'maxTransitDays': max_transit_days,
            'recommendedShippingLine': recommended_line,
            'availableShippingLines': shipping_result.get('available', []),
            'shippingRegion': shipping_result.get('region', ''),
            'selectionMode': shipping_result.get('selection_mode', 'fastest'),
            'filteredCount': shipping_result.get('filtered_count', 0),
            'totalShippingLines': shipping_result.get('total_count', 0),
        }
    })


# ===== 海运费合约查询（读取本地合约信息导出0806.xlsx）=====

import pandas as pd
import re as _re

# 合约数据内存缓存（带刷新TTL）
_CONTRACT_CACHE = None
_CONTRACT_CACHE_TIME = 0


def _load_contract_data():
    """加载并缓存合约海运费Excel数据，按TTL自动刷新"""
    global _CONTRACT_CACHE, _CONTRACT_CACHE_TIME
    now = time.time()
    if _CONTRACT_CACHE is not None and (now - _CONTRACT_CACHE_TIME) < config.CONTRACT_FREIGHT_CACHE_TTL:
        return _CONTRACT_CACHE

    fpath = config.CONTRACT_FREIGHT_FILE
    if not os.path.exists(fpath):
        print(f"[合约运费] 文件不存在: {fpath}")
        return pd.DataFrame()

    try:
        df = pd.read_excel(fpath, sheet_name=0)
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
        # 清洗数值列
        for col in ['20GP报价', '40GP报价', '40HC报价', '45HC报价']:
            if col in df.columns:
                df[col] = pd.to_numeric(df[col], errors='coerce')
        # 日期列
        for col in ['合约生效日期', '合约失效日期']:
            if col in df.columns:
                df[col] = pd.to_datetime(df[col], errors='coerce')

        _CONTRACT_CACHE = df
        _CONTRACT_CACHE_TIME = now
        print(f"[合约运费] 加载完成: {df.shape[0]} 条记录, {df.shape[1]} 列")
        return df
    except Exception as e:
        print(f"[合约运费] 加载失败: {e}")
        return pd.DataFrame()


def _contract_port_match(contract_port_list, target_port):
    """判断合约里的港口列表（逗号分隔，可能多港）是否包含目标港口

    支持合约格式: "CNSHA / 上海/SHANGHAI, CNNBO / 宁波/NINGBO"
    支持目标格式: "上海/SHANGHAI" / "上海" / "SHANGHAI" / "洛杉矶/LOS ANGELES,CA"
    """
    if not contract_port_list or pd.isna(contract_port_list):
        return False
    if not target_port:
        return False

    target = str(target_port).strip()
    # 去掉目标里的州代码后缀
    target_clean = _re.sub(r',\s*[A-Z]{2,3}\s*$', '', target).strip()
    target_upper = target_clean.upper()
    target_chinese = target_clean.split('/')[0].strip() if '/' in target_clean else target_clean
    target_english = target_clean.split('/')[-1].strip() if '/' in target_clean else target_clean
    # 再去除英文里的州后缀
    target_english = _re.sub(r',\s*[A-Z]{2,3}\s*$', '', target_english).strip()

    # 合约港口按逗号拆分（多港）
    contract_ports = [p.strip() for p in str(contract_port_list).split(',') if p.strip()]
    for cp in contract_ports:
        cp_upper = cp.upper()
        # 方式1: 目标中文名包含在合约港口里
        if target_chinese and target_chinese in cp:
            return True
        # 方式2: 目标英文名包含在合约港口里
        if target_english and target_english.upper() in cp_upper:
            return True
        # 方式3: 目标整体名的一部分包含
        if target_clean and target_clean in cp:
            return True
        # 方式4: LOCODE 匹配（合约里的XXXXX前缀）
        locode_match = _re.match(r'^([A-Z]{2}[A-Z0-9]{3})\s*/', cp)
        if locode_match and target_upper and locode_match.group(1) in target_upper:
            return True
    return False


def _contract_find_rates(df, origin, destination, box_type):
    """从合约表中查找匹配的航线报价，返回匹配行列表

    返回: list[dict] — 每个元素包含船公司、报价、币种、生效/失效日期等
    """
    if df.empty:
        return []

    box_col = config.CONTRACT_BOX_COLUMNS.get(box_type, '40HC报价')
    if box_col not in df.columns:
        return []

    # 过滤出箱型报价非空的行
    valid = df[df[box_col].notna() & (df[box_col] > 0)].copy()
    if valid.empty:
        return []

    # 匹配起运港和目的港
    origin_mask = valid['起运港'].apply(lambda x: _contract_port_match(x, origin))
    dest_mask = valid['目的港'].apply(lambda x: _contract_port_match(x, destination))
    matched = valid[origin_mask & dest_mask].copy()

    if matched.empty:
        # 更宽松：目的港用运抵国（中文名）包含匹配
        dest_chinese = str(destination).split('/')[0].strip() if '/' in str(destination) else str(destination)
        if dest_chinese and len(dest_chinese) >= 2:
            dest_mask_loose = valid['目的港'].apply(lambda x: dest_chinese in str(x))
            matched = valid[origin_mask & dest_mask_loose].copy()

    results = []
    for _, row in matched.iterrows():
        rate = float(row[box_col])
        # 判断合约是否有效（当前日期在生效/失效之间）
        today = pd.Timestamp.now().normalize()
        effective_from = row['合约生效日期'] if '合约生效日期' in row and pd.notna(row['合约生效日期']) else None
        effective_to = row['合约失效日期'] if '合约失效日期' in row and pd.notna(row['合约失效日期']) else None
        is_valid = True
        if effective_from and today < effective_from:
            is_valid = False
        if effective_to and today > effective_to:
            is_valid = False

        results.append({
            'carrier': row.get('船公司简称', ''),
            'origin': row.get('起运港', ''),
            'destination': row.get('目的港', ''),
            'rate': rate,
            'currency': str(row.get('币种', 'USD')),
            'effectiveFrom': effective_from.strftime('%Y-%m-%d') if effective_from and pd.notna(effective_from) else None,
            'effectiveTo': effective_to.strftime('%Y-%m-%d') if effective_to and pd.notna(effective_to) else None,
            'isValid': is_valid,
            'note': str(row.get('备注', '')) if pd.notna(row.get('备注', '')) else '',
        })

    # 有效优先，然后按价格升序
    results.sort(key=lambda r: (0 if r['isValid'] else 1, r['rate']))
    return results


@app.route('/api/freight-rate', methods=['GET'])
def get_freight_rate():
    """海运费合约查询接口（读取合约信息导出0806.xlsx）

    参数:
        origin      — 起运港（如 "上海/SHANGHAI"）
        destination — 目的港/运抵国（如 "洛杉矶/LOS ANGELES" 或 "美国"）
        boxType     — 箱型 20GP/40GP/40HQ/45HQ（默认 40HQ）
    """
    origin = request.args.get('origin', '上海/SHANGHAI')
    destination = request.args.get('destination', '洛杉矶/LOS ANGELES')
    box_type = request.args.get('boxType', '40HQ')

    # 箱型参数规范化容错
    bt = str(box_type).strip().upper()
    if bt in ('40HC', '40HQ', '40H'):
        box_type_norm = '40HQ'
    elif bt == '45HC' or bt == '45HQ':
        box_type_norm = '45HQ'
    elif bt == '20GP':
        box_type_norm = '20GP'
    elif bt == '40GP':
        box_type_norm = '40GP'
    else:
        box_type_norm = '40HQ'

    df = _load_contract_data()
    if df.empty:
        return jsonify({
            'success': False,
            'error': '合约运费文件未找到或加载失败',
            'hint': f'请确认文件存在: {config.CONTRACT_FREIGHT_FILE}',
        }), 500

    matched = _contract_find_rates(df, origin, destination, box_type_norm)
    unit = config.CONTRACT_BOX_UNIT.get(box_type_norm, 'FEU')

    if not matched:
        return jsonify({
            'success': False,
            'error': f'合约中未找到匹配航线: {origin} → {destination} ({box_type_norm})',
            'hint': '请调整起运港/目的港/箱型，或手动输入海运费金额',
            'query': {
                'origin': origin,
                'destination': destination,
                'boxType': box_type_norm,
            },
        }), 404

    rates = [m['rate'] for m in matched if m['isValid']]
    if not rates:
        rates = [m['rate'] for m in matched]  # 没有有效则用全部

    min_rate = min(rates)
    max_rate = max(rates)
    median_rate = round((min_rate + max_rate) / 2, 2) if len(rates) > 1 else min_rate

    # 取前8家船公司报价展示
    quotes = matched[:8]
    currency = quotes[0]['currency'] if quotes else 'USD'

    # 有效性概览
    valid_count = sum(1 for m in matched if m['isValid'])
    total_count = len(matched)

    result = {
        'success': True,
        'source': '合约信息导出0806.xlsx',
        'data': {
            'origin': origin,
            'destination': destination,
            'boxType': box_type_norm,
            'currency': currency,
            'unit': unit,
            'minRate': round(min_rate, 2),
            'maxRate': round(max_rate, 2),
            'medianRate': round(median_rate, 2),
            'avgRate': round(sum(rates) / len(rates), 2),
            'quotes': quotes,
            'quoteCount': total_count,
            'validQuoteCount': valid_count,
            'fileUpdate': time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(os.path.getmtime(config.CONTRACT_FREIGHT_FILE)))
            if os.path.exists(config.CONTRACT_FREIGHT_FILE) else None,
            'fetchedAt': datetime.now().isoformat(),
            'matchStrategy': 'exact' if valid_count > 0 else ('loose' if matched else 'none'),
        }
    }
    print(f"[合约运费] 查询: {origin}→{destination} {box_type_norm} "
          f"→ 匹配{total_count}条（有效{valid_count}条）, "
          f"min={min_rate} max={max_rate} median={median_rate}")
    return jsonify(result)


@app.route('/api/freight-rate-batch', methods=['POST'])
def get_freight_rate_batch():
    """批量海运费合约查询接口

    请求体 JSON:
    {
        "routes": [
            {"origin": "上海/SHANGHAI", "destination": "洛杉矶/LOS ANGELES", "boxType": "40HQ"},
            {"origin": "青岛/QINGDAO", "destination": "鹿特丹/ROTTERDAM", "boxType": "40HQ"}
        ]
    }
    """
    data = request.get_json()
    if not data or 'routes' not in data:
        return jsonify({'error': '请求体不能为空，需要 routes 数组'}), 400

    routes = data['routes']
    if not isinstance(routes, list) or len(routes) == 0:
        return jsonify({'error': 'routes 必须是非空数组'}), 400

    df = _load_contract_data()
    results = []
    errors = []

    for i, route in enumerate(routes):
        try:
            origin = route.get('origin', '上海/SHANGHAI')
            destination = route.get('destination', '')
            bt = route.get('boxType', '40HQ')
            bt_norm = '40HQ'
            bt_s = str(bt).strip().upper()
            if bt_s in ('40HC', '40HQ'):
                bt_norm = '40HQ'
            elif bt_s == '45HC' or bt_s == '45HQ':
                bt_norm = '45HQ'
            elif bt_s == '20GP':
                bt_norm = '20GP'
            elif bt_s == '40GP':
                bt_norm = '40GP'

            matched = _contract_find_rates(df, origin, destination, bt_norm)
            if matched:
                rates = [m['rate'] for m in matched if m['isValid']] or [m['rate'] for m in matched]
                min_r = min(rates)
                max_r = max(rates)
                med_r = round((min_r + max_r) / 2, 2) if len(rates) > 1 else min_r
                unit = config.CONTRACT_BOX_UNIT.get(bt_norm, 'FEU')
                results.append({
                    'index': i,
                    'origin': origin,
                    'destination': destination,
                    'boxType': bt_norm,
                    'success': True,
                    'minRate': round(min_r, 2),
                    'maxRate': round(max_r, 2),
                    'medianRate': round(med_r, 2),
                    'currency': (matched[0]['currency'] if matched else 'USD'),
                    'unit': unit,
                    'quoteCount': len(matched),
                    'validQuoteCount': sum(1 for m in matched if m['isValid']),
                    'quotes': matched[:5],
                })
            else:
                errors.append({
                    'index': i,
                    'origin': origin,
                    'destination': destination,
                    'boxType': bt_norm,
                    'success': False,
                    'error': '未匹配到合约报价',
                })
        except Exception as e:
            errors.append({
                'index': i,
                'success': False,
                'error': f'处理异常: {str(e)[:120]}',
            })
            origin = route.get('origin', '上海/SHANGHAI')
            destination = route.get('destination', '洛杉矶/LOS ANGELES')
            box_type = route.get('boxType', '40HQ')

            bt_norm = '40HQ'
            bt_s = str(box_type).strip().upper()
            if bt_s in ('40HC', '40HQ'):
                bt_norm = '40HQ'
            elif bt_s == '45HC' or bt_s == '45HQ':
                bt_norm = '45HQ'
            elif bt_s == '20GP':
                bt_norm = '20GP'
            elif bt_s == '40GP':
                bt_norm = '40GP'

            matched = _contract_find_rates(df, origin, destination, bt_norm)
            if matched:
                rates = [m['rate'] for m in matched if m['isValid']] or [m['rate'] for m in matched]
                min_r = min(rates)
                max_r = max(rates)
                med_r = round((min_r + max_r) / 2, 2) if len(rates) > 1 else min_r
                unit = config.CONTRACT_BOX_UNIT.get(bt_norm, 'FEU')
                results.append({
                    'index': i,
                    'origin': origin,
                    'destination': destination,
                    'boxType': bt_norm,
                    'minRate': round(min_r, 2),
                    'maxRate': round(max_r, 2),
                    'medianRate': round(med_r, 2),
                    'currency': (matched[0]['currency'] if matched else 'USD'),
                    'unit': unit,
                    'quoteCount': len(matched),
                    'validQuoteCount': sum(1 for m in matched if m['isValid']),
                    'quotes': matched[:5],
                    'success': True,
                })
            else:
                errors.append({
                    'index': i,
                    'route': route,
                    'error': '未匹配到合约报价',
                    'success': False,
                })

        except Exception as e:
            errors.append({
                'index': i,
                'route': route,
                'error': str(e),
                'success': False,
            })

    return jsonify({
        'success': True,
        'source': '合约信息导出0806.xlsx',
        'totalRoutes': len(routes),
        'successCount': len(results),
        'failCount': len(errors),
        'results': results,
        'errors': errors,
        'fetchedAt': datetime.now().isoformat(),
    })


# ===== 船公司海运费比价接口 =====

def _contract_find_carrier_rates_multi(df, origin, destination, box_types):
    """从合约表中查找所有匹配的船公司，并返回各箱型报价

    返回: dict — {carrier_name: {boxType: rate, ...}}
    """
    if df.empty:
        return {}

    # 匹配航线
    origin_mask = df['起运港'].apply(lambda x: _contract_port_match(x, origin))
    dest_mask = df['目的港'].apply(lambda x: _contract_port_match(x, destination))
    route_matched = df[origin_mask & dest_mask].copy()

    if route_matched.empty:
        # 宽松匹配：目的港用中文名包含
        dest_chinese = str(destination).split('/')[0].strip() if '/' in str(destination) else str(destination)
        if dest_chinese and len(dest_chinese) >= 2:
            dest_mask_loose = df['目的港'].apply(lambda x: dest_chinese in str(x))
            route_matched = df[origin_mask & dest_mask_loose].copy()

    if route_matched.empty:
        return {}

    # 确定箱型→列名映射
    box_col_map = {}
    for bt in box_types:
        bt_s = str(bt).strip().upper()
        if bt_s in ('40HC', '40HQ'):
            col = '40HC报价'
        elif bt_s in ('45HC', '45HQ'):
            col = '45HC报价'
        elif bt_s == '20GP':
            col = '20GP报价'
        elif bt_s == '40GP':
            col = '40GP报价'
        else:
            continue
        if col in route_matched.columns:
            box_col_map[bt] = col

    if not box_col_map:
        return {}

    # 按船公司分组，收集各箱型报价（取有效的最低报价）
    today = pd.Timestamp.now().normalize()
    carrier_rates = {}

    for _, row in route_matched.iterrows():
        carrier = str(row.get('船公司简称', '')).strip()
        if not carrier:
            continue

        # 判断合约有效期
        effective_from = row.get('合约生效日期') if '合约生效日期' in row else None
        effective_to = row.get('合约失效日期') if '合约失效日期' in row else None
        is_valid = True
        if pd.notna(effective_from) and today < effective_from:
            is_valid = False
        if pd.notna(effective_to) and today > effective_to:
            is_valid = False

        if carrier not in carrier_rates:
            carrier_rates[carrier] = {'isValid': is_valid, 'rates': {}}
        else:
            # 如果已有记录且新的是有效的，保留有效的
            if is_valid and not carrier_rates[carrier]['isValid']:
                carrier_rates[carrier]['isValid'] = True

        # 收集各箱型报价（取最低价）
        for bt, col in box_col_map.items():
            val = row[col]
            if pd.notna(val) and float(val) > 0:
                rate = float(val)
                existing = carrier_rates[carrier]['rates'].get(bt)
                if existing is None or rate < existing:
                    carrier_rates[carrier]['rates'][bt] = rate

        # 币种
        if '币种' in row and pd.notna(row['币种']):
            carrier_rates[carrier]['currency'] = str(row['币种'])

    return carrier_rates


@app.route('/api/freight-rate-compare', methods=['POST'])
def compare_freight_rates():
    """船公司海运费比价接口 — 返回各船公司的各箱型报价及总价排序

    请求体 JSON:
    {
        "origin": "上海/SHANGHAI",
        "destination": "洛杉矶/LOS ANGELES",
        "boxTypes": {"40HQ": 5, "20GP": 3}
    }
    """
    data = request.get_json()
    if not data or 'boxTypes' not in data:
        return jsonify({'error': '请求体不能为空，需要 boxTypes 参数'}), 400

    origin = data.get('origin', '上海/SHANGHAI')
    destination = data.get('destination', '洛杉矶/LOS ANGELES')
    box_types_qty = data.get('boxTypes', {})
    if not isinstance(box_types_qty, dict) or len(box_types_qty) == 0:
        return jsonify({'error': 'boxTypes 必须是非空字典，如 {"40HQ": 5, "20GP": 3}'}), 400

    df = _load_contract_data()
    if df.empty:
        return jsonify({'success': False, 'error': '合约运费文件未找到或加载失败'}), 500

    # 获取各船公司的各箱型报价
    carrier_rates = _contract_find_carrier_rates_multi(df, origin, destination, list(box_types_qty.keys()))

    if not carrier_rates:
        return jsonify({
            'success': False,
            'error': f'合约中未找到匹配航线: {origin} → {destination}',
            'hint': '请调整起运港/目的港，或手动输入海运费',
        }), 404

    # 为每个船公司计算总价
    usd_to_cny = 7.2
    carriers = []
    for carrier_name, info in carrier_rates.items():
        total_cny = 0
        per_type_detail = {}
        has_all_types = True

        for bt, qty in box_types_qty.items():
            rate = info['rates'].get(bt)
            if rate is None:
                has_all_types = False
                per_type_detail[bt] = {'rate': None, 'qty': qty, 'subtotalCny': None}
            else:
                currency = info.get('currency', 'USD')
                rate_cny = rate * usd_to_cny if currency == 'USD' else rate
                subtotal = round(rate_cny * qty, 2)
                total_cny += subtotal
                per_type_detail[bt] = {
                    'rate': rate,
                    'rateCny': round(rate_cny, 2),
                    'qty': qty,
                    'subtotalCny': subtotal,
                    'currency': currency,
                }

        # 只有至少有一种箱型报价的船公司才加入比较
        has_any_rate = any(d['rate'] is not None for d in per_type_detail.values())
        if not has_any_rate:
            continue

        carriers.append({
            'carrier': carrier_name,
            'isValid': info['isValid'],
            'totalCny': round(total_cny, 2),
            'totalUsd': round(total_cny / usd_to_cny, 2),
            'perTypeDetail': per_type_detail,
            'hasAllTypes': has_all_types,
            'currency': info.get('currency', 'USD'),
        })

    # 按总价升序排列（便宜的在前面），有效的优先
    carriers.sort(key=lambda c: (0 if c['isValid'] else 1, c['totalCny']))

    return jsonify({
        'success': True,
        'source': '合约信息导出0806.xlsx',
        'data': {
            'origin': origin,
            'destination': destination,
            'boxTypes': box_types_qty,
            'carriers': carriers,
            'carrierCount': len(carriers),
            'cheapest': carriers[0] if carriers else None,
            'fetchedAt': datetime.now().isoformat(),
        }
    })


# ===== 高速费 LLM 估算接口 =====

@app.route('/api/estimate-toll', methods=['POST'])
def estimate_toll():
    """调用LLM估算工厂自运到港口的高速公路通行费

    请求体 JSON:
    {
        "province": "安徽",
        "originPort": "上海/SHANGHAI",
        "boxCount": 10,
        "boxTypes": ["40HQ", "20GP"],
        "weight": 15000,
        "volume": 76
    }
    """
    data = request.get_json()
    if not data:
        return jsonify({'error': '请求体不能为空'}), 400

    province = data.get('province', '')
    origin_port = data.get('originPort', '上海/SHANGHAI')
    box_count = int(data.get('boxCount', 1) or 1)
    box_types = data.get('boxTypes', ['40HQ'])
    weight = float(data.get('weight', 0) or 0)
    volume = float(data.get('volume', 0) or 0)

    if not province:
        return jsonify({'error': '缺少 province 参数'}), 400

    eng = get_engine()
    toll = eng.llm_client.estimate_toll_fee(province, origin_port, box_count, box_types, weight, volume)

    return jsonify({
        'success': True,
        'data': {
            'province': province,
            'originPort': origin_port,
            'boxCount': box_count,
            'tollFee': toll,
            'source': 'llm' if config.LLM_ENABLED else 'rule_engine',
            'generatedAt': datetime.now().isoformat(),
        }
    })


if __name__ == '__main__':
    print("=" * 60)
    print("物流运输路径智能优化 API 服务 v3")
    print("基于7张核心数据表 + 规则/LLM双引擎")
    print("=" * 60)
    print(f"LLM 模式: {'启用 (' + config.LLM_MODEL + ')' if config.LLM_ENABLED else '未启用（使用规则引擎）'}")
    print(f"监听地址: http://{config.HOST}:{config.PORT}")
    print(f"数据源: {len(config.FILES)} 张Excel表")
    print("=" * 60)

    # 预加载
    print("\n[预加载] 正在加载数据并构建知识库...")
    get_engine()
    print("[预加载] 完成\n")

    app.run(host=config.HOST, port=config.PORT, debug=True)


# ===== 港杂费推荐接口 =====

# 港杂费标准表缓存
_PORT_MISC_CACHE = None
_PORT_MISC_CACHE_TIME = 0

def _load_port_misc_data():
    global _PORT_MISC_CACHE, _PORT_MISC_CACHE_TIME
    now = __import__('time').time()
    if _PORT_MISC_CACHE is not None and (now - _PORT_MISC_CACHE_TIME) < 3600:
        return _PORT_MISC_CACHE
    fpath = config.PORT_MISC_STANDARD_FILE
    if not os.path.exists(fpath):
        print(f"[港杂费标准] 文件不存在: {fpath}")
        return pd.DataFrame()
    try:
        df = pd.read_excel(fpath, sheet_name=0)
        _PORT_MISC_CACHE = df
        _PORT_MISC_CACHE_TIME = now
        print(f"[港杂费标准] 加载完成: {df.shape[0]} 条记录")
        return df
    except Exception as e:
        print(f"[港杂费标准] 加载失败: {e}")
        return pd.DataFrame()


@app.route('/api/port-misc-fee', methods=['GET'])
def get_port_misc_fee():
    """港杂费推荐接口 — 根据始发港/贸易条款/箱型推荐港杂费

    参数:
        originPort  — 始发港（如 上海/SHANGHAI）
        tradeTerm   — 贸易条款（FOB/CIF/DDP），传 auto/智能推荐/空 时跳过贸易条款匹配
        boxType     — 箱型（40HQ/20GP等）

    匹配逻辑:
        1. 贸易条款为 auto/智能推荐/空 → 直接按 始发港 + 箱型 匹配
        2. 否则按 始发港 + 贸易条款 + 箱型 匹配，无结果回退到 始发港 + 箱型
        3. 优先选择数据等级为"标准"的行，取其中最便宜的推荐标准(中位数)
    """
    origin = request.args.get('originPort', '')
    trade_term = request.args.get('tradeTerm', '')
    box_type = request.args.get('boxType', '40HQ')

    if not origin:
        return jsonify({'error': '缺少 originPort 参数'}), 400

    # 规范化箱型
    bt = str(box_type).strip().upper()
    if bt in ('40HC', '40HQ'): bt_norm = '40HQ'
    elif bt in ('45HC', '45HQ'): bt_norm = '45HQ'
    elif bt == '20GP': bt_norm = '20GP'
    elif bt == '40GP': bt_norm = '40GP'
    else: bt_norm = bt

    df = _load_port_misc_data()
    if df.empty:
        return jsonify({'success': False, 'error': '港杂费标准文件未找到'}), 500

    # 匹配始发港
    origin_mask = df['始发港'].apply(lambda x: _contract_port_match(x, origin))
    # 匹配箱型
    box_mask = df['箱型'].str.strip().str.upper() == bt_norm

    # 判断是否需要按贸易条款匹配
    skip_term = (not trade_term or trade_term.strip() in ('auto', '智能推荐'))
    match_desc = f'{origin} / {bt_norm}'

    if not skip_term:
        # 三键匹配：始发港 + 贸易条款 + 箱型
        term_mask = df['贸易条款'].str.strip().str.upper() == trade_term.strip().upper()
        matched = df[origin_mask & term_mask & box_mask].copy()
        match_desc = f'{origin} / {trade_term} / {bt_norm}'
        if matched.empty:
            # 回退：三键无结果 → 两键（始发港 + 箱型）
            matched = df[origin_mask & box_mask].copy()
            match_desc = f'{origin} / {bt_norm}（回退，贸易条款{trade_term}无匹配）'
    else:
        # 贸易条款为 auto/智能推荐/空，直接用始发港 + 箱型匹配
        matched = df[origin_mask & box_mask].copy()
        match_desc = f'{origin} / {bt_norm}（贸易条款=auto，跳过）'

    if matched.empty:
        print(f'[港杂费] 无匹配: {match_desc}')
        return jsonify({
            'success': False,
            'error': f'未找到匹配的港杂费标准: {match_desc}',
        }), 404

    # 优先选择数据等级为"标准"的行，取其中最便宜的推荐标准(中位数)
    standard_rows = matched[matched['数据等级'].str.strip() == '标准']
    if not standard_rows.empty:
        matched_for_best = standard_rows
        used_level = '标准'
    else:
        matched_for_best = matched
        used_level = matched['数据等级'].iloc[0] if len(matched) > 0 else '参考'

    best_row = matched_for_best.loc[matched_for_best['推荐标准(中位数)'].idxmin()]
    best_fee = float(best_row['推荐标准(中位数)'])

    # 返回所有匹配行（按数据等级排序：标准优先，再按费用升序）
    matched['_sort_level'] = matched['数据等级'].apply(lambda x: 0 if str(x).strip() == '标准' else 1)
    matched = matched.sort_values(['_sort_level', '推荐标准(中位数)']).drop(columns=['_sort_level'])

    recommendations = []
    for _, row in matched.iterrows():
        recommendations.append({
            'carrier': row.get('承运商', ''),
            'sampleCount': int(row.get('样本数', 0)),
            'recommendedFee': float(row.get('推荐标准(中位数)', 0)),
            'lowerBound': float(row.get('合理下限(P10)', 0)),
            'upperBound': float(row.get('合理上限(P90)', 0)),
            'avgFee': float(row.get('去离群后均值', 0)),
            'dataLevel': row.get('数据等级', ''),
        })

    # 推荐值：数据等级"标准"中最便宜的推荐标准(中位数)
    best = best_fee

    return jsonify({
        'success': True,
        'data': {
            'originPort': origin,
            'tradeTerm': trade_term,
            'boxType': bt_norm,
            'recommendedFee': round(best, 2),
            'usedLevel': used_level,
            'bestCarrier': str(best_row.get('承运商', '')),
            'recommendations': recommendations,
            'totalMatched': len(matched),
            'fetchedAt': datetime.now().isoformat(),
        }
    })


# ===== 陆运费推荐（各路线报价卡） =====

_ROUTE_PRICING_CACHE = None
_ROUTE_PRICING_CACHE_TIME = None
_ROUTE_PRICING_CACHE_TTL = 600  # 10分钟缓存


def _load_route_pricing_data():
    """加载各路线报价卡 Excel 文件（带缓存）"""
    global _ROUTE_PRICING_CACHE, _ROUTE_PRICING_CACHE_TIME
    now = time.time()
    if _ROUTE_PRICING_CACHE is not None and _ROUTE_PRICING_CACHE_TIME is not None:
        if now - _ROUTE_PRICING_CACHE_TIME < _ROUTE_PRICING_CACHE_TTL:
            return _ROUTE_PRICING_CACHE
    fpath = config.ROUTE_PRICING_FILE
    if not os.path.exists(fpath):
        print(f"[路线报价卡] 文件不存在: {fpath}")
        return None
    try:
        xl = pd.ExcelFile(fpath)
        _ROUTE_PRICING_CACHE = xl
        _ROUTE_PRICING_CACHE_TIME = now
        print(f"[路线报价卡] 加载完成: {len(xl.sheet_names)} 个 Sheet")
        return xl
    except Exception as e:
        print(f"[路线报价卡] 加载失败: {e}")
        return None


def _find_route_sheet(xl, factory_name, origin_port):
    """在 Excel 的所有 Sheet 中查找匹配工厂+始发港的 Sheet"""
    if xl is None:
        return None

    import re
    # 提取工厂核心名称（去掉后缀差异：用品/制品/科技等）
    factory_core = factory_name
    match = re.search(r'(.+英科.+?)(?:医疗|用品|制品|科技|卫生|印刷).*$', factory_name)
    if match:
        factory_core = match.group(1)

    # 提取始发港中文名
    port_short = origin_port.split('/')[0] if '/' in origin_port else origin_port

    candidates = []
    for sname in xl.sheet_names:
        # 跳过说明/汇总 Sheet（00-04 和 99 开头的 Sheet）
        prefix = sname.split('_')[0] if '_' in sname else ''
        if prefix in ('00', '01', '02', '03', '04', '99'):
            continue
        # 检查 Sheet 名是否包含港口名
        if port_short not in sname:
            continue
        # 检查 Sheet 名是否包含工厂名（精确或核心部分）
        if factory_name in sname:
            candidates.append((sname, 2))
        elif factory_core and factory_core in sname:
            candidates.append((sname, 1))

    if not candidates:
        return None

    candidates.sort(key=lambda x: x[1], reverse=True)
    return candidates[0][0]


# 运输方式映射（前端值 → Excel 中文值）
TRANSPORT_MODE_MAP = {
    'direct': '直拖',
    'seaRail': '海铁',
    'factorySelf': '工厂自运',
    'landToWater': '陆改水',
}


@app.route('/api/land-freight', methods=['GET'])
def get_land_freight():
    """陆运费推荐接口 — 根据发货工厂/始发港/运输方式推荐陆运费"""
    factory = request.args.get('factory', '')
    origin_port = request.args.get('originPort', '')
    transport_mode = request.args.get('transportMode', 'direct')
    box_type = request.args.get('boxType', '40HQ')

    if not factory:
        return jsonify({'error': '缺少 factory 参数'}), 400
    if not origin_port:
        return jsonify({'error': '缺少 originPort 参数'}), 400

    mode_cn = TRANSPORT_MODE_MAP.get(transport_mode, transport_mode)
    bt = str(box_type).strip().upper()

    xl = _load_route_pricing_data()
    if xl is None:
        return jsonify({'success': False, 'error': '各路线报价卡文件未找到'}), 500

    sheet_name = _find_route_sheet(xl, factory, origin_port)
    if sheet_name is None:
        return jsonify({
            'success': False,
            'error': f'未找到匹配的路线报价 Sheet: 工厂={factory}, 港口={origin_port}',
        }), 404

    try:
        df = pd.read_excel(xl, sheet_name=sheet_name)
    except Exception as e:
        return jsonify({'success': False, 'error': f'读取 Sheet 失败: {str(e)}'}), 500

    if df.empty or df.shape[1] < 5:
        return jsonify({'success': False, 'error': f'Sheet [{sheet_name}] 数据为空'}), 404

    # 列结构: 0=运输方式, 1=公司, 2=箱型, 3=样本数, 4=陆运费中位数(元)
    #         5=高速费中位数(元), 6=陆运+高速中位数(元), 7=陆运+高速均值(元)
    col_mode = df.columns[0]
    col_box = df.columns[2]
    col_land_median = df.columns[4]
    col_toll_median = df.columns[5]

    # 按运输方式筛选
    mode_mask = df[col_mode].astype(str).str.strip() == mode_cn
    mode_matched = df[mode_mask]

    if mode_matched.empty:
        mode_mask = df[col_mode].astype(str).str.contains(mode_cn, na=False)
        mode_matched = df[mode_mask]

    if mode_matched.empty:
        all_modes = df[col_mode].dropna().unique().tolist()
        return jsonify({
            'success': False,
            'error': f'Sheet [{sheet_name}] 中未找到运输方式 [{mode_cn}]，可用: {all_modes}',
        }), 404

    # 按箱型筛选；无匹配时放宽
    box_mask = mode_matched[col_box].astype(str).str.strip().str.upper() == bt
    if box_mask.any():
        candidates = mode_matched[box_mask].copy()
    else:
        candidates = mode_matched.copy()

    if candidates.empty:
        return jsonify({
            'success': False,
            'error': f'Sheet [{sheet_name}] 中未找到运输方式[{mode_cn}]箱型[{bt}]的数据',
        }), 404

    # 取 陆运费中位数(元) 最小的行
    best_idx = candidates[col_land_median].idxmin()
    best_row = candidates.loc[best_idx]
    best_land_fee = float(best_row[col_land_median])
    best_toll_fee = float(best_row[col_toll_median]) if pd.notna(best_row[col_toll_median]) else 0

    candidates_sorted = candidates.sort_values(col_land_median)
    all_quotes = []
    for _, row in candidates_sorted.head(20).iterrows():
        all_quotes.append({
            'carrier': str(row.get(df.columns[1], '')) if df.shape[1] > 1 else '',
            'boxType': str(row.get(col_box, '')),
            'sampleCount': int(row.get(df.columns[3], 0)) if df.shape[1] > 3 and pd.notna(row.get(df.columns[3])) else 0,
            'landFreightMedian': float(row.get(col_land_median, 0)) if pd.notna(row.get(col_land_median)) else 0,
            'tollFreightMedian': float(row.get(col_toll_median, 0)) if pd.notna(row.get(col_toll_median)) else 0,
        })

    return jsonify({
        'success': True,
        'data': {
            'factory': factory,
            'originPort': origin_port,
            'transportMode': transport_mode,
            'transportModeCn': mode_cn,
            'boxType': bt,
            'sheetName': sheet_name,
            'recommendedLandFreight': round(best_land_fee, 2),
            'recommendedTollFreight': round(best_toll_fee, 2),
            'recommendedCarrier': str(best_row.get(df.columns[1], '')),
            'sampleCount': int(best_row.get(df.columns[3], 0)) if pd.notna(best_row.get(df.columns[3])) else 0,
            'allQuotes': all_quotes,
            'totalMatched': len(candidates),
            'fetchedAt': datetime.now().isoformat(),
        }
    })

