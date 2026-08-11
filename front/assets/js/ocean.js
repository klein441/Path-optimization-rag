/**
 * 海运费实时报价 / 船公司合约比价
 * 表单页与结果页共享同一份 store.ocean 状态，天然双向同步，
 * 无需再通过 DOM id（oceanXxx / fpOceanXxx）互相拷贝。
 */
import { store } from './state.js';
import { apiRouteInfo, apiFreightRateCompare, fetchPortMiscFee } from './api.js';
import { initLandFees } from './fees.js';
import { getFallbackFactory, getOceanPortsByCountry } from './utils.js';

export function updateRouteInfoCard(factory, originPort, destPort) {
    store.routeInfoCard.factory = factory || '—';
    store.routeInfoCard.origin = originPort || '—';
    store.routeInfoCard.dest = destPort || '—';
}

// 选择船公司报价卡：更新费用数据（表单页与结果页同时生效）
export function selectOceanCarrier(carrier) {
    if (!carrier) return;
    if (store.feeConfirmed) return; // 费用已确认，不允许再切换船公司
    store.feeData.ocean.fee = carrier.totalCny;
    store.feeModified['海运费'] = true; // 用户选择船公司视为手动修改海运费
    store.feeData.ocean.selectedCarrier = carrier;
    store.feeData.ocean.allCarriers = store.ocean.carriers;
    store.ocean.medianRateText = '$' + Number(carrier.totalUsd).toLocaleString();
    console.log('[海运费] 用户选择船公司:', carrier.carrier, '¥' + carrier.totalCny);
}

export async function fetchOceanFreightRate() {
    store.ocean.loading = true;
    store.ocean.realtime = false;
    store.ocean.error = false;

    const form = store.form;
    const productTypes = form.productTypes.slice();
    const productType = productTypes[0] || '';
    const destCountry = form.destCountry || '';
    const boxTypes = form.boxTypes.slice();
    if (boxTypes.length === 0) boxTypes.push('40HQ');
    const cargoReady = form.cargoReady || '';
    const shipSchedule = form.shipSchedule || '';

    let routeInfo = null;
    let origin, destination;

    // Step 1: 通过后端知识库获取工厂→始发港 和 运抵国→目的港
    try {
        const params = {
            productType: productType,
            destCountry: destCountry,
            cargoReady: cargoReady,
            shipSchedule: shipSchedule,
            boxType: boxTypes[0],
        };
        const routeResult = await apiRouteInfo(params);

        if (routeResult.success && routeResult.data) {
            routeInfo = routeResult.data;
            origin = routeInfo.originPort;
            destination = routeInfo.destPort;
            console.log('[海运费] 路线查询成功:',
                routeInfo.factoryShort, '→', origin, '→', destination,
                '| 推荐航司:', routeInfo.recommendedShippingLine?.name || '无');

            // 自动推荐陆运费（根据工厂省份+路线报价卡）
            if (!store.feeData._fromRecommendation) {
                initLandFees(routeInfo.factoryProvince, 'direct',
                             routeInfo.factory || '', routeInfo.originPort || '');
            }

            // 自动推荐港杂费（根据始发港+贸易条款+箱型查询标准表）
            if (!store.feeData._fromRecommendation) {
                fetchPortMiscFee(origin, form.tradePref || '', boxTypes);
            }

            updateRouteInfoCard(routeInfo.factoryShort || routeInfo.factory || '',
                                routeInfo.originPort || '',
                                routeInfo.destPort || '');
        } else {
            console.warn('[海运费] 路线查询失败，回退到默认映射:', routeResult.error);
            const fallback = getOceanPortsByCountry(destCountry);
            origin = fallback.origin;
            destination = fallback.destination;
            const factoryInfo = getFallbackFactory(origin);
            updateRouteInfoCard(factoryInfo.factoryShort, origin, destination);
            if (!store.feeData._fromRecommendation) {
                fetchPortMiscFee(origin, form.tradePref || '', boxTypes);
            }
        }
    } catch (e) {
        console.warn('[海运费] 路线查询异常，回退到默认映射:', e.message);
        const fallback = getOceanPortsByCountry(destCountry);
        origin = fallback.origin;
        destination = fallback.destination;
        const factoryInfo = getFallbackFactory(origin);
        updateRouteInfoCard(factoryInfo.factoryShort, origin, destination);
        if (!store.feeData._fromRecommendation) {
            fetchPortMiscFee(origin, form.tradePref || '', boxTypes);
        }
    }

    // 使用表单中选择的终到港（如有），否则回退到路线推荐的目的港
    var selectedDestPort = (form.destPort || '').trim();
    if (selectedDestPort) {
        destination = selectedDestPort;
    }

    // Step 2: 调用船公司比价接口
    try {
        const boxTypesQty = {};
        boxTypes.forEach(bt => { boxTypesQty[bt] = form.boxTypeCounts[bt] || 1; });

        const result = await apiFreightRateCompare(origin, destination, boxTypesQty);

        if (result.success && result.data) {
            const d = result.data;
            // 过滤：只保留对所有选定箱型都有报价的船公司
            const allCarriers = (d.carriers || []).filter(function(c) { return c.hasAllTypes; });
            const carriers = allCarriers;
            const realCheapest = carriers.length > 0 ? carriers[0] : null;

            // 价格摘要（USD总价）
            store.ocean.medianRateText = realCheapest ? '$' + Number(realCheapest.totalUsd).toLocaleString() : '—';
            store.ocean.boxTypeKeys = Object.keys(boxTypesQty);

            // 航线信息
            const boxTypeSummary = boxTypes.map(function(bt) {
                return bt + '×' + (form.boxTypeCounts[bt] || 1);
            }).join(' + ');
            store.ocean.routeInfoText = origin + ' → ' + destination + ' · ' + boxTypeSummary;

            // 转运天数 / 船公司数量
            const transitParts = [];
            if (routeInfo && routeInfo.transitDays) transitParts.push(routeInfo.transitDays + '天转运');
            transitParts.push(carriers.length + '家船公司');
            store.ocean.transitInfoText = transitParts.join(' · ');

            // 获取时间
            store.ocean.fetchedAtText = '📄 合约表 · ' + (d.fetchedAt
                ? new Date(d.fetchedAt).toLocaleString('zh-CN', { month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit' })
                : '刚刚');

            // 推荐航司信息
            if (routeInfo && routeInfo.recommendedShippingLine) {
                var rec = routeInfo.recommendedShippingLine;
                store.ocean.shippingLineText = '推荐航司: ' + rec.name + ' (' + rec.code + ') · ' + rec.transit_days + '天 · ' + rec.frequency;
            }
            // 工厂标签
            if (routeInfo) {
                store.ocean.factoryTagText = routeInfo.factoryShort + ' · ' + origin;
            }

            store.ocean.carriers = carriers;
            store.ocean.realtime = true;
            store.ocean.error = false;

            // 自动将最便宜船公司总价填入（只要拿到合约报价就覆盖后端历史估算值）
            if (realCheapest && !store.feeConfirmed) {
                store.feeData.ocean.fee = realCheapest.totalCny;
                store.feeData.ocean.cheapestCarrier = realCheapest;
                store.feeData.ocean.allCarriers = carriers;
                store.feeData.ocean.selectedCarrier = realCheapest;
            } else if (realCheapest) {
                store.feeData.ocean.cheapestCarrier = realCheapest;
                store.feeData.ocean.allCarriers = carriers;
            }

            console.log('[海运费] 船公司比价成功:', origin, '→', destination,
                allCarriers.length + '家(全箱型' + carriers.length + '家), 最低: ' + (realCheapest ? realCheapest.carrier + ' ¥' + realCheapest.totalCny : '无'));
        } else {
            throw new Error(result.error || '未获取到海运费报价数据');
        }
    } catch (e) {
        console.error('[海运费] 合约报价获取失败:', e);
        store.ocean.realtime = false;
        store.ocean.error = true;

        const msg = e.message || '';
        if (msg.includes('未找到匹配') || msg.includes('未匹配') || msg.includes('404')) {
            store.ocean.errorDesc = '该航线未在合约文件中找到匹配报价，请调整港口/箱型，或手动输入海运费金额';
        } else if (msg.includes('文件未找到') || msg.includes('加载失败')) {
            store.ocean.errorDesc = '合约运费文件加载失败，请确认文件存在或手动输入海运费';
        } else if (msg.includes('Failed to fetch') || msg.includes('NetworkError')) {
            store.ocean.errorDesc = '后端服务未启动或无法连接，请启动后端（py main.py）后重试';
        } else {
            store.ocean.errorDesc = msg || '获取合约报价失败，请手动输入海运费金额';
        }
    } finally {
        store.ocean.loading = false;
    }
}