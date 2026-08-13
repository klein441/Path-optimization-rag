/**
 * API 请求封装
 */
import { API_BASE } from './constants.js';
import { store } from './state.js';

async function getJSON(url) {
    const resp = await fetch(url);
    return resp.json();
}

// ===== 运抵国列表 =====
export async function apiGetCountries() {
    const data = await getJSON(API_BASE + '/api/countries-source');
    if (data.success && data.data.countries.length > 0) return data.data.countries;
    return [];
}

// ===== 运抵国对应终到港列表 =====
export async function apiGetDestPorts(country) {
    const data = await getJSON(API_BASE + '/api/dest-ports?country=' + encodeURIComponent(country));
    if (data.success && data.data.ports.length > 0) return data.data.ports;
    return [];
}

// ===== 航线信息（工厂 → 始发港，运抵国 → 目的港）=====
export async function apiRouteInfo(params) {
    const url = new URL('/api/route-info', API_BASE);
    Object.keys(params).forEach(k => { if (params[k]) url.searchParams.set(k, params[k]); });
    const resp = await fetch(url.toString());
    return resp.json();
}

// ===== 船公司合约比价 =====
export async function apiFreightRateCompare(origin, destination, boxTypesQty) {
    const resp = await fetch(API_BASE + '/api/freight-rate-compare', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ origin: origin, destination: destination, boxTypes: boxTypesQty }),
    });
    return resp.json();
}

// ===== 港杂费标准表查询 =====
export async function apiPortMiscFee(originPort, tradeTerm, boxType) {
    const tt = (tradeTerm && tradeTerm !== 'auto' && tradeTerm !== '智能推荐') ? tradeTerm : '';
    const url = API_BASE + '/api/port-misc-fee?originPort=' + encodeURIComponent(originPort) +
        '&tradeTerm=' + encodeURIComponent(tt) + '&boxType=' + encodeURIComponent(boxType);
    const resp = await fetch(url);
    return resp.json();
}

// ===== 陆运费路线报价卡查询 =====
export async function apiLandFreight(factory, originPort, transportMode, boxType) {
    const url = API_BASE + '/api/land-freight?factory=' + encodeURIComponent(factory) +
        '&originPort=' + encodeURIComponent(originPort) +
        '&transportMode=' + encodeURIComponent(transportMode || 'direct') +
        '&boxType=' + encodeURIComponent(boxType);
    const resp = await fetch(url);
    return resp.json();
}

// ===== 工厂自运高速费 LLM 估算 =====
export async function apiEstimateToll(payload) {
    const resp = await fetch(API_BASE + '/api/estimate-toll', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload),
    });
    return resp.json();
}

// ===== 智能路径推荐 =====
export async function apiRecommend(payload) {
    const resp = await fetch(API_BASE + '/api/logistics/recommend', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload),
    });
    if (!resp.ok) throw new Error('HTTP ' + resp.status);
    return resp.json();
}

// ===== 费用信息确认后回写数据库 =====
export async function apiConfirmFees(payload) {
    const resp = await fetch(API_BASE + '/api/recommendation/confirm', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload),
    });
    return resp.json();
}

// ===== 港杂费推荐（根据始发港/贸易条款/柜型查询标准表）=====
export async function fetchPortMiscFee(originPort, tradeTerm, boxTypes) {
    if (!originPort || originPort === '—') return;
    var bt = (boxTypes && boxTypes.length > 0) ? boxTypes[0] : '40HQ';
    var pm = store.feeData.portMisc;
    pm.loading = true;
    pm.error = false;
    try {
        const result = await apiPortMiscFee(originPort, tradeTerm, bt);
        if (result.success && result.data) {
            var perBoxFee = result.data.recommendedFee;
            var totalBoxes = parseInt(store.form.boxes) || 1;
            var fee = Math.round(perBoxFee * totalBoxes * 100) / 100;
            pm.fee = fee;
            pm.perBoxFee = perBoxFee;
            pm.bestCarrier = result.data.bestCarrier || '';
            pm.carriers = result.data.recommendations || [];
            pm.totalMatched = result.data.totalMatched || 0;
            pm.usedLevel = result.data.usedLevel || '';
            pm.source = '港杂费标准_贸易条款承运商箱型港口.xlsx';
            // 自动选中推荐承运商（最便宜）
            pm.selectedCarrier = (pm.carriers.length > 0) ? pm.carriers[0] : null;
            pm.error = false;
            console.log('[港杂费] 推荐:', originPort, tradeTerm, bt,
                '单柜¥' + perBoxFee + ' × ' + totalBoxes + '柜 = ¥' + fee,
                '| 承运商:', pm.bestCarrier,
                '(' + result.data.totalMatched + '条标准记录)');
        } else {
            pm.error = true;
            pm.carriers = [];
            pm.bestCarrier = '';
            pm.selectedCarrier = null;
        }
    } catch (e) {
        console.warn('[港杂费] 查询失败:', e.message);
        pm.error = true;
        pm.carriers = [];
        pm.selectedCarrier = null;
    } finally {
        pm.loading = false;
    }
}

// ===== 陆运费推荐（从工厂到起运港拖车费表实时查询）=====
export async function fetchLandFreightFromRoute(factoryName, originPort, transportMode) {
    if (!factoryName || !originPort) return;
    var boxTypes = store.form.boxTypes.slice();
    var bt = (boxTypes && boxTypes.length > 0) ? boxTypes[0] : '40HQ';
    var ld = store.feeData.land;
    ld.loading = true;
    ld.error = false;
    try {
        const result = await apiLandFreight(factoryName, originPort, transportMode, bt);
        if (result.success && result.data) {
            var d = result.data;
            var landFee = d.recommendedLandFreight;
            var tollFeeRec = d.recommendedTollFreight || 0;
            if (landFee > 0) {
                var totalBoxes = parseInt(store.form.boxes) || 1;
                store.feeData.land.baseFreight = Math.round(landFee * totalBoxes * 100) / 100;
                store.feeData.land.perBoxFee = landFee;
            }
            if (tollFeeRec > 0) store.feeData.land.tollFee = tollFeeRec;
            // 承运商推荐数据
            ld.bestCarrier = d.recommendedCarrier || '';
            ld.carriers = d.allQuotes || [];
            ld.totalMatched = d.totalMatched || 0;
            ld.source = '工厂到起运港拖车费_运输方式承运商发货工厂始发港.xlsx';
            // 自动选中后端按加权中位数推荐的承运商
            var recCarrier = d.recommendedCarrier || '';
            ld.selectedCarrier = null;
            for (var i = 0; i < ld.carriers.length; i++) {
                if (ld.carriers[i].carrier === recCarrier) {
                    ld.selectedCarrier = ld.carriers[i];
                    break;
                }
            }
            if (!ld.selectedCarrier && ld.carriers.length > 0) ld.selectedCarrier = ld.carriers[0];
            ld.error = false;
            console.log('[陆运费] 路线报价卡推荐:', factoryName, originPort, transportMode,
                '陆运费¥' + landFee, '高速费¥' + tollFeeRec,
                '| 承运商:', ld.bestCarrier,
                '(Sheet: ' + d.sheetName + ', ' + d.totalMatched + '条记录)');
        } else {
            ld.error = true;
            ld.carriers = [];
            ld.bestCarrier = '';
            ld.selectedCarrier = null;
            console.warn('[陆运费] 路线报价卡未匹配:', result.error || '无数据，使用默认值');
        }
    } catch (e) {
        console.warn('[陆运费] 查询失败:', e.message);
        ld.error = true;
        ld.carriers = [];
        ld.selectedCarrier = null;
    } finally {
        ld.loading = false;
    }
}
