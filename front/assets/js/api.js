/**
 * API 请求封装
 */
import { API_BASE } from './constants.js';
import { store } from './state.js';
import { getLandBoxTypes, applyLandFreightTotal } from './utils.js';

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
    const boxTypes = getLandBoxTypes();
    const ld = store.feeData.land;
    ld.loading = true;
    ld.error = false;
    ld.recommendedRatesByType = {};
    ld.selectedRatesByType = {};
    ld.selectedCarrierByType = {};
    ld.carriers = [];
    ld.totalMatched = 0;
    try {
        const results = await Promise.all(boxTypes.map(bt => apiLandFreight(factoryName, originPort, transportMode, bt)));
        let hasSuccess = false;
        let hasError = false;
        let totalToll = 0;
        let bestCarrier = '';
        let allQuotes = [];
        results.forEach((result, idx) => {
            const bt = boxTypes[idx];
            if (result && result.success && result.data) {
                hasSuccess = true;
                const d = result.data;
                const rate = parseFloat(d.recommendedLandFreight) || 0;
                ld.recommendedRatesByType[bt] = rate;
                ld.selectedRatesByType[bt] = rate;
                (d.allQuotes || []).forEach(q => {
                    if (!q.carrier) return;
                    allQuotes.push(Object.assign({}, q, { boxType: bt }));
                });
                const recommendedQuote = (d.allQuotes || []).find(q => q.carrier === d.recommendedCarrier) || (d.allQuotes || [])[0];
                if (recommendedQuote) {
                    ld.selectedCarrierByType[bt] = Object.assign({}, recommendedQuote, { boxType: bt });
                }
                totalToll += parseFloat(d.recommendedTollFreight) || 0;
                if (!bestCarrier) bestCarrier = d.recommendedCarrier || '';
                ld.totalMatched += d.totalMatched || 0;
            } else {
                hasError = true;
            }
        });
        if (hasSuccess) {
            ld.bestCarrier = bestCarrier;
            ld.carriers = allQuotes;
            ld.source = '工厂到起运港拖车费_运输方式承运商发货工厂始发港.xlsx';
            if (totalToll > 0) ld.tollFee = totalToll;
            applyLandFreightTotal();
            // 自动选中后端按加权中位数推荐的承运商
            const recCarrier = bestCarrier || '';
            ld.selectedCarrier = null;
            for (let i = 0; i < ld.carriers.length; i++) {
                if (ld.carriers[i].carrier === recCarrier) {
                    ld.selectedCarrier = ld.carriers[i];
                    break;
                }
            }
            if (!ld.selectedCarrier && ld.carriers.length > 0) ld.selectedCarrier = ld.carriers[0];
            ld.error = hasError;
            console.log('[陆运费] 路线报价卡推荐:', factoryName, originPort, transportMode,
                '陆运费¥' + store.feeData.land.baseFreight, '高速费¥' + totalToll,
                '| 承运商:', ld.bestCarrier,
                '(Sheet: 工厂到起运港拖车费_运输方式承运商发货工厂始发港.xlsx, ' + ld.totalMatched + '条记录)');
        } else {
            ld.error = true;
            ld.carriers = [];
            ld.bestCarrier = '';
            ld.selectedCarrier = null;
            console.warn('[陆运费] 路线报价卡未匹配:', hasError ? '部分箱型无数据' : '无数据，使用默认值');
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
