"""
Flask API 服务器 — 物流运输路径智能优化后端（基于8张数据表重新设计）

接口：
  POST /api/logistics/recommend  — 获取推荐方案
  GET  /api/logistics/knowledge  — 获取知识库摘要
  GET  /api/logistics/factories  — 获取工厂列表
  GET  /api/logistics/countries  — 获取所有运抵国列表
  GET  /api/logistics/country-info — 获取指定运抵国详情
  GET  /api/logistics/health     — 健康检查
  GET  /api/freight-rate         — 海运费实时查询（Freightos API代理，支持持久化缓存）
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

    # 1. 根据产品类型找最优工厂（产能最高）
    factories = kb.get_factory_by_product(product_type)
    if not factories:
        # 回退：使用所有工厂
        for name, info in kb.factory_info.items():
            factories.append({"name": name, "info": info})

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

    # 4. 港口名→Freightos代码
    origin_code = _resolve_freightos_port(origin_port_clean)
    dest_code = _resolve_freightos_port(dest_port_clean)

    # 5. 箱型→Freightos loadtype
    load_type = _resolve_freightos_box(box_type)
    is_fcl = 'container' in load_type or 'reefer' in load_type

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


# ===== 海运费实时查询（Freightos API 代理）=====

FREIGHTOS_API_URL = "https://ship.freightos.com/api/shippingCalculator"

# Freightos 需要浏览器User-Agent，python-requests默认UA会被限流
_FREIGHTOS_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
    "Referer": "https://www.freightos.com/",
}

# 持久化缓存 + 智能限流保护
_CACHE_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "_freightos_cache.json")
_FREIGHTOS_CACHE_TTL = 3600      # 新鲜缓存：1小时
_FREIGHTOS_STALE_TTL = 86400     # 降级缓存：24小时（过期但仍可展示）
_FREIGHTOS_COOLDOWN = 1800       # 遇到429后冷却30分钟，不再尝试请求


def _load_cache():
    """从磁盘加载缓存"""
    if os.path.exists(_CACHE_FILE):
        try:
            with open(_CACHE_FILE, 'r', encoding='utf-8') as f:
                data = json_module.load(f)
                print(f"[Freightos] 从磁盘加载了 {len(data.get('entries', {}))} 条缓存记录")
                return data
        except Exception as e:
            print(f"[Freightos] 缓存文件读取失败: {e}")
    return {"entries": {}, "last_429": None}


def _save_cache(cache_data):
    """保存缓存到磁盘"""
    try:
        # 清理过期超过24小时的条目
        now = time.time()
        cache_data["entries"] = {
            k: v for k, v in cache_data["entries"].items()
            if now - v["time"] < _FREIGHTOS_STALE_TTL
        }
        with open(_CACHE_FILE, 'w', encoding='utf-8') as f:
            json_module.dump(cache_data, f, ensure_ascii=False, default=str)
    except Exception as e:
        print(f"[Freightos] 缓存写入失败: {e}")


_freightos_cache = _load_cache()


def _clean_port_name(port_name):
    """清理港口名中的州/省代码后缀（如 ',CA', ',TX'）
    例如：'洛杉矶/LOS ANGELES,CA' → '洛杉矶/LOS ANGELES'
    """
    if not port_name:
        return port_name
    import re
    return re.sub(r',\s*[A-Z]{2,3}\s*$', '', str(port_name)).strip()


def _resolve_freightos_port(port_name):
    """将系统内部港口名映射为 Freightos 港口代码"""
    if not port_name:
        return config.FREIGHTOS_FALLBACK_PORT

    # 清理：去掉州/省代码后缀（如 ",CA", ",TX"）和多余空格
    import re
    cleaned = re.sub(r',\s*[A-Z]{2,3}\s*$', '', str(port_name)).strip()
    port_name_upper = cleaned.upper()
    # 精确匹配
    if port_name in config.FREIGHTOS_PORT_MAP:
        return config.FREIGHTOS_PORT_MAP[port_name]
    if port_name_upper in config.FREIGHTOS_PORT_MAP:
        return config.FREIGHTOS_PORT_MAP[port_name_upper]
    # 模糊匹配：尝试提取关键港口名
    for key, code in config.FREIGHTOS_PORT_MAP.items():
        if key.upper() == port_name_upper:
            return code
    # 包含匹配
    for key, code in config.FREIGHTOS_PORT_MAP.items():
        if port_name_upper in key.upper():
            return code
    # 最后回退到上海
    return config.FREIGHTOS_FALLBACK_PORT


def _resolve_freightos_box(box_type):
    """将系统箱型映射为 Freightos loadtype"""
    return config.FREIGHTOS_BOX_MAP.get(box_type, "container40")


@app.route('/api/freight-rate', methods=['GET'])
def get_freight_rate():
    """海运费实时查询接口（代理 Freightos API）"""
    origin = request.args.get('origin', '上海/SHANGHAI')
    destination = request.args.get('destination', '洛杉矶/LOS ANGELES')
    box_type = request.args.get('boxType', '40HQ')
    weight = request.args.get('weight', '15000')
    quantity = request.args.get('quantity', '1')

    origin_code = _resolve_freightos_port(origin)
    dest_code = _resolve_freightos_port(destination)
    load_type = _resolve_freightos_box(box_type)

    cache_key = f"{origin_code}|{dest_code}|{load_type}|{weight}|{quantity}"
    cache_entry = _freightos_cache["entries"].get(cache_key)

    # 新鲜缓存命中（1小时内）
    if cache_entry and (time.time() - cache_entry['time']) < _FREIGHTOS_CACHE_TTL:
        resp_data = cache_entry['data'].copy()
        resp_data['data']['cached'] = True
        resp_data['data']['cachedAt'] = datetime.fromtimestamp(cache_entry['time']).isoformat()
        resp_data['data']['fetchedAt'] = resp_data['data'].get('fetchedAt', resp_data['data']['cachedAt'])
        print(f"[Freightos] 缓存命中: {origin_code}→{dest_code}")
        return jsonify(resp_data)

    # 降级缓存（过期但仍有数据可展示）
    stale_cache = cache_entry

    # 限流冷却检查：如果最近遇到过429，先冷却一段时间
    last_429 = _freightos_cache.get("last_429")
    if last_429:
        cooldown_remaining = _FREIGHTOS_COOLDOWN - (time.time() - last_429)
        if cooldown_remaining > 0:
            cooldown_min = int(cooldown_remaining / 60) + 1
            print(f"[Freightos] 冷却中（{cooldown_min}分钟后解禁），跳过API请求")
            if stale_cache:
                stale_cache['data']['data']['stale'] = True
                stale_cache['data']['data']['staleWarning'] = f'API冷却中（{cooldown_min}分钟后自动重试），显示缓存数据'
                stale_cache['data']['data']['cached'] = True
                stale_cache['data']['data']['cachedAt'] = datetime.fromtimestamp(stale_cache['time']).isoformat()
                return jsonify(stale_cache['data'])
            return jsonify({
                'success': False,
                'error': f'Freightos API 限流保护中（约{cooldown_min}分钟后自动恢复）',
                'hint': '请稍后再试，或手动输入海运费金额',
                'cooldownMinutes': cooldown_min,
            }), 429
        else:
            # 冷却期结束，清除标记
            _freightos_cache["last_429"] = None
            _save_cache(_freightos_cache)

    # 构建 Freightos 请求
    params = {
        "loadtype": load_type,
        "weight": weight,
        "origin": origin_code,
        "quantity": quantity,
        "destination": dest_code,
    }

    raw_data = None
    http_error = None
    resp = None

    # 构建查询URL
    query_string = "&".join([f"{k}={v}" for k, v in params.items()])
    full_url = f"{FREIGHTOS_API_URL}?{query_string}"

    try:
        # Step 1: 尝试 Python requests（带浏览器UA）
        resp = requests.get(FREIGHTOS_API_URL, params=params, timeout=15, headers=_FREIGHTOS_HEADERS)

        if resp.status_code == 429:
            # Python请求被限流 → 回退到 curl 子进程
            print("[Freightos] Python请求429，回退到curl...")
            import subprocess
            curl_result = subprocess.run([
                "curl", "-s", "--max-time", "15",
                "-H", "User-Agent: Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
                "-H", "Accept: application/json, text/plain, */*",
                "-H", "Accept-Language: zh-CN,zh;q=0.9,en;q=0.8",
                full_url
            ], capture_output=True, text=True, timeout=18)

            curl_output = curl_result.stdout.strip()
            if curl_output and curl_output.startswith('{'):
                raw_data = json_module.loads(curl_output)
                print("[Freightos] curl成功获取数据")
            else:
                # curl也失败 → 启动冷却
                _freightos_cache["last_429"] = time.time()
                _save_cache(_freightos_cache)
                print("[Freightos] curl也失败，启动冷却")
                if stale_cache:
                    stale_cache['data']['data']['stale'] = True
                    stale_cache['data']['data']['staleWarning'] = 'Freightos API 限流，显示缓存数据'
                    stale_cache['data']['data']['cached'] = True
                    return jsonify(stale_cache['data'])
                return jsonify({
                    'success': False,
                    'error': 'Freightos API 限流 (HTTP 429)',
                    'hint': '已启动30分钟冷却保护，请稍后再试或手动输入海运费',
                }), 429
        else:
            resp.raise_for_status()
            raw_data = resp.json()

    except requests.exceptions.Timeout:
        if stale_cache:
            stale_cache['data']['data']['stale'] = True
            stale_cache['data']['data']['staleWarning'] = 'API超时，显示缓存数据'
            stale_cache['data']['data']['cached'] = True
            return jsonify(stale_cache['data'])
        return jsonify({'success': False, 'error': 'API请求超时', 'hint': '请检查网络连接或稍后重试'}), 504
    except requests.exceptions.HTTPError:
        http_error = True
    except requests.exceptions.ConnectionError:
        if stale_cache:
            stale_cache['data']['data']['stale'] = True
            stale_cache['data']['data']['staleWarning'] = '无法连接API，显示缓存数据'
            stale_cache['data']['data']['cached'] = True
            return jsonify(stale_cache['data'])
        return jsonify({'success': False, 'error': '无法连接到 Freightos API', 'hint': '请检查网络连接'}), 502
    except subprocess.TimeoutExpired:
        if stale_cache:
            stale_cache['data']['data']['stale'] = True
            stale_cache['data']['data']['staleWarning'] = 'curl超时，显示缓存数据'
            stale_cache['data']['data']['cached'] = True
            return jsonify(stale_cache['data'])
        pass
    except Exception as e:
        if stale_cache:
            stale_cache['data']['data']['stale'] = True
            stale_cache['data']['data']['staleWarning'] = f'API异常: {str(e)[:80]}'
            stale_cache['data']['data']['cached'] = True
            return jsonify(stale_cache['data'])
        return jsonify({'success': False, 'error': f'请求异常: {str(e)[:150]}'}), 502

    if raw_data is None:
        if http_error and stale_cache:
            stale_cache['data']['data']['stale'] = True
            stale_cache['data']['data']['staleWarning'] = f'Freightos API 错误 (HTTP {resp.status_code})，显示缓存数据'
            stale_cache['data']['data']['cached'] = True
            stale_cache['data']['data']['cachedAt'] = datetime.fromtimestamp(stale_cache['time']).isoformat()
            return jsonify(stale_cache['data'])
        if http_error:
            return jsonify({
                'success': False,
                'error': f'Freightos API 返回错误: HTTP {resp.status_code}',
            }), resp.status_code
        return jsonify({'success': False, 'error': '未知错误'}), 500

    # 解析 Freightos 响应
    # Freightos API 可能在 response 外套一层 {"response": {...}}
    # 也可能直接返回 {...}，两种格式都兼容
    mode_data = {}
    estimated = raw_data.get('estimatedFreightRates', {})
    if not estimated and 'response' in raw_data:
        estimated = raw_data.get('response', {}).get('estimatedFreightRates', {})
    if estimated:
        mode_data = estimated.get('mode', {})

    price_data = mode_data.get('price', {})
    min_rate = price_data.get('min', {}).get('moneyAmount', {}).get('amount', 0) if price_data else 0
    max_rate = price_data.get('max', {}).get('moneyAmount', {}).get('amount', 0) if price_data else 0
    median_rate = round((min_rate + max_rate) / 2, 2) if min_rate and max_rate else 0

    transit = mode_data.get('transitTimes', {})
    transit_days = None
    if transit:
        t_min = transit.get('min', 0)
        t_max = transit.get('max', 0)
        if t_min and t_max:
            transit_days = f"{t_min}-{t_max}"

    mode_type = mode_data.get('mode', 'FCL')
    num_quotes = estimated.get('numQuotes', 0)

    result = {
        'success': True,
        'source': 'Freightos',
        'data': {
            'origin': origin,
            'originCode': origin_code,
            'destination': destination,
            'destinationCode': dest_code,
            'boxType': box_type,
            'loadType': load_type,
            'weight': float(weight),
            'quantity': int(quantity),
            'minRate': min_rate,
            'maxRate': max_rate,
            'medianRate': median_rate,
            'currency': 'USD',
            'mode': mode_type,
            'numQuotes': num_quotes,
            'unit': 'FEU' if load_type in ('container40', 'container40hc', 'container45hc') else 'TEU',
            'transitDays': transit_days,
            'raw': raw_data,
            'fetchedAt': datetime.now().isoformat(),
            'cached': False,
        }
    }

    # 写入持久化缓存
    _freightos_cache["entries"][cache_key] = {
        'time': time.time(),
        'data': result
    }
    _save_cache(_freightos_cache)
    print(f"[Freightos] 缓存已持久化: {origin_code}→{dest_code} min=${min_rate} max=${max_rate}")

    return jsonify(result)


@app.route('/api/freight-rate-batch', methods=['POST'])
def get_freight_rate_batch():
    """批量海运费查询接口（用于一次性获取多个航线价格）

    请求体 JSON:
    {
        "routes": [
            {"origin": "上海/SHANGHAI", "destination": "洛杉矶/LOS ANGELES", "boxType": "40HQ", "weight": 15000, "quantity": 1},
            {"origin": "青岛/QINGDAO", "destination": "鹿特丹/ROTTERDAM", "boxType": "40HQ", "weight": 15000, "quantity": 1}
        ]
    }
    """
    data = request.get_json()
    if not data or 'routes' not in data:
        return jsonify({'error': '请求体不能为空，需要 routes 数组'}), 400

    routes = data['routes']
    if not isinstance(routes, list) or len(routes) == 0:
        return jsonify({'error': 'routes 必须是非空数组'}), 400

    results = []
    errors = []

    for i, route in enumerate(routes):
        try:
            origin = route.get('origin', '上海/SHANGHAI')
            destination = route.get('destination', '洛杉矶/LOS ANGELES')
            box_type = route.get('boxType', '40HQ')
            weight = route.get('weight', '15000')
            quantity = route.get('quantity', '1')

            origin_code = _resolve_freightos_port(origin)
            dest_code = _resolve_freightos_port(destination)
            load_type = _resolve_freightos_box(box_type)

            params = {
                "loadtype": load_type,
                "weight": weight,
                "origin": origin_code,
                "quantity": quantity,
                "destination": dest_code,
            }

            resp = requests.get(FREIGHTOS_API_URL, params=params, timeout=15, headers=_FREIGHTOS_HEADERS)
            resp.raise_for_status()
            raw_data = resp.json()

            # 解析 Freightos 嵌套格式（兼容 response 包装）
            estimated = raw_data.get('estimatedFreightRates', {})
            if not estimated and 'response' in raw_data:
                estimated = raw_data.get('response', {}).get('estimatedFreightRates', {})
            mode_data = estimated.get('mode', {}) if estimated else {}
            price_data = mode_data.get('price', {})

            min_rate = price_data.get('min', {}).get('moneyAmount', {}).get('amount', 0) if price_data else 0
            max_rate = price_data.get('max', {}).get('moneyAmount', {}).get('amount', 0) if price_data else 0
            median_rate = round((min_rate + max_rate) / 2, 2) if min_rate and max_rate else 0

            transit = mode_data.get('transitTimes', {})
            transit_days = None
            if transit:
                t_min = transit.get('min', 0)
                t_max = transit.get('max', 0)
                if t_min and t_max:
                    transit_days = f"{t_min}-{t_max}"

            results.append({
                'index': i,
                'origin': origin,
                'destination': destination,
                'boxType': box_type,
                'minRate': min_rate,
                'maxRate': max_rate,
                'medianRate': median_rate,
                'currency': 'USD',
                'transitDays': transit_days,
                'mode': mode_data.get('mode', 'FCL'),
                'success': True,
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
        'totalRoutes': len(routes),
        'successCount': len(results),
        'failCount': len(errors),
        'results': results,
        'errors': errors,
        'fetchedAt': datetime.now().isoformat(),
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
