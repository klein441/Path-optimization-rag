"""
Flask API 服务器 — 物流运输路径智能优化后端（基于8张数据表重新设计）

接口：
  POST /api/logistics/recommend  — 获取推荐方案
  GET  /api/logistics/knowledge  — 获取知识库摘要
  GET  /api/logistics/factories  — 获取工厂列表
  GET  /api/logistics/countries  — 获取所有运抵国列表
  GET  /api/logistics/country-info — 获取指定运抵国详情
  GET  /api/logistics/health     — 健康检查
"""
import sys
import os
from datetime import datetime
from flask import Flask, request, jsonify
from flask_cors import CORS

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
