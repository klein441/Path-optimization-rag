/**
 * 费用计算与费用面板逻辑
 */
import { TRANSPORT_MODE_FREIGHT, USD_TO_CNY } from './constants.js';
import { store } from './state.js';
import { getOriginPortByProvince, isFTradeTerm } from './utils.js';
import { apiEstimateToll, fetchLandFreightFromRoute } from './api.js';

export function getSeaManagerTotal() {
    const sm = store.feeData.seaManager;
    const totalBoxes = parseInt(store.form.boxes) || 1;
    return sm.manifestFee * totalBoxes + sm.vgmFee * totalBoxes + sm.ics2Fee;
}

export function getOtherTotal() {
    return store.feeData.other.reduce((sum, o) => sum + (parseFloat(o.amount) || 0), 0);
}

export function getFixedTotal() {
    return store.feeData.fixed.reduce((sum, o) => sum + (parseFloat(o.amount) || 0), 0);
}

export function calculateAllFees() {
    const fd = store.feeData;
    const landTotal = fd.land.baseFreight + fd.land.tollFee + fd.land.insideLoadFee;
    const term = (store.results.primary && store.results.primary.tradeTerm) || store.form.tradePref || '';
    const oceanFee = isFTradeTerm(term) ? 0 : fd.ocean.fee;
    return landTotal + getSeaManagerTotal() + fd.portMisc.fee + oceanFee + getOtherTotal();
}

export function buildConfirmedFeeItems() {
    const fd = store.feeData;
    const totalBoxes = parseInt(store.form.boxes) || 1;
    const term = (store.results.primary && store.results.primary.tradeTerm) || store.form.tradePref || '';
    const items = [];
    const push = (name, category, amount, basis) => {
        const amt = Math.round((parseFloat(amount) || 0) * 100) / 100;
        if (amt <= 0) return;
        items.push({
            name: name,
            category: category,
            amount_cny: amt,
            amount_usd: Math.round(amt / USD_TO_CNY * 100) / 100,
            basis: basis || '用户确认',
            modified_by_user: true,
        });
    };

    push('陆运费', '工厂到起运港拖车费', fd.land.baseFreight, '用户确认');
    push('高速费', '工厂到起运港拖车费', fd.land.tollFee, '用户确认');
    push('内装费', '工厂到起运港拖车费', fd.land.insideLoadFee, '用户确认');
    push('舱单费', '海管家费用', fd.seaManager.manifestFee * totalBoxes, '用户确认');
    push('VGM费', '海管家费用', fd.seaManager.vgmFee * totalBoxes, '用户确认');
    push('ICS2费', '海管家费用', fd.seaManager.ics2Fee, '用户确认');
    push('港杂费', '出口起运港港杂费', fd.portMisc.fee, '用户确认');
    if (!isFTradeTerm(term)) {
        push('海运费', '出口海运费', fd.ocean.fee, '用户确认');
    }
    (fd.fixed || []).forEach(function (f) {
        push(f.name || '固定费用', '其他费用', f.amount, '用户确认');
    });
    (fd.other || []).forEach(function (o) {
        push(o.name || '其他费用', '其他费用', o.amount, '用户确认');
    });
    return items;
}

// ===== 陆运费初始化（根据工厂省份和运输方式自动推荐）=====
// factoryName 和 originPort 可选：传入时从工厂到起运港拖车费表实时查询陆运费
export function initLandFees(province, mode, factoryName, originPort) {
    const fd = store.feeData;
    fd.land.factoryProvince = province || '';
    if (factoryName) fd.land.factoryName = factoryName;
    if (originPort) fd.land.originPort = originPort;
    mode = mode || 'direct';
    const conf = TRANSPORT_MODE_FREIGHT[mode];
    if (!conf) return;
    fd.land.transportMode = mode;
    var totalBoxes = parseInt(store.form.boxes) || 1;
    fd.land.baseFreight = Math.round(conf.baseFreight * totalBoxes * 100) / 100;
    fd.land.perBoxFee = conf.baseFreight;
    if (factoryName && originPort) {
        fetchLandFreightFromRoute(factoryName, originPort, mode);
    }
    if (conf.hasToll) {
        fd.land.tollEnabled = true;
        if (province) {
            calculateTollFee();
        } else {
            fd.land.tollFee = 50;
        }
    } else {
        fd.land.tollEnabled = false;
        fd.land.tollFee = 0;
    }
    fd.land.insideLoadEnabled = false;
    fd.land.insideLoadFee = 0;
}

// ===== 工厂自运高速费 LLM 智能计算（调用后端 DeepSeek LLM）=====
export async function calculateTollFee() {
    const fd = store.feeData;
    var province = fd.land.factoryProvince || '';
    var boxCount = parseInt(store.form.boxes) || 1;
    var boxTypes = store.form.boxTypes.slice();
    if (boxTypes.length === 0) boxTypes = ['40HQ'];
    var weight = parseFloat(store.form.weight) || 0;
    var volume = parseFloat(store.form.volume) || 0;

    var originPort = store.routeInfoCard.origin || '';
    if (!originPort || originPort === '—') {
        originPort = getOriginPortByProvince(province);
    }

    if (!province) {
        console.warn('[高速费] 缺少工厂省份信息，使用默认值50');
        applyTollFee(50);
        return;
    }

    try {
        var result = await apiEstimateToll({
            province: province,
            originPort: originPort,
            boxCount: boxCount,
            boxTypes: boxTypes,
            weight: weight,
            volume: volume,
        });
        if (result.success && result.data && result.data.tollFee > 0) {
            var toll = result.data.tollFee;
            applyTollFee(toll);
            console.log('[高速费] LLM计算完成: 省份=' + province + ', 港口=' + originPort +
                ', 柜数=' + boxCount + ', 高速费=¥' + toll + ' (来源: ' + (result.data.source || 'llm') + ')');
        } else {
            console.warn('[高速费] LLM返回异常，回退默认值:', result);
            applyTollFee(80);
        }
    } catch (e) {
        console.warn('[高速费] LLM调用失败，回退默认值:', e.message);
        applyTollFee(80);
    }
}

export function applyTollFee(amount) {
    store.feeData.land.tollFee = amount;
    store.feeData.land.tollEnabled = true;
}

// ===== 从后端推荐结果同步 feeData =====
export function applyResultToFeeData(data) {
    var primary = data.primary;
    if (!primary || !primary.cost || !primary.cost.items) return;
    const fd = store.feeData;

    // 费用面板的工厂/港口必须和推荐结果保持一致
    fd.fixed = [];
    fd.land.factoryName = primary.factory || fd.land.factoryName;
    fd.land.originPort = primary.departurePort || fd.land.originPort;
    if (primary.factoryInfo && primary.factoryInfo.province) {
        fd.land.factoryProvince = primary.factoryInfo.province;
    }
    store.routeInfoCard.factory = primary.factoryShort || primary.factory || store.routeInfoCard.factory;
    store.routeInfoCard.origin = primary.departurePort || store.routeInfoCard.origin;
    store.routeInfoCard.dest = primary.destPort || store.routeInfoCard.dest;
    store.ocean.factoryTagText = (primary.factoryShort || primary.factory || '') + ' · ' + (primary.departurePort || '');

    var items = primary.cost.items;
    var oceanModified = false; // 海运费是否来自用户手动修改（重新优化时保留用户确认值）
    function setOtherFee(name, amount) {
        for (var j = 0; j < fd.other.length; j++) {
            if ((fd.other[j].name || '') === name) {
                fd.other[j].amount = amount;
                return;
            }
        }
        fd.other.push({ name: name, amount: amount });
    }
    for (var i = 0; i < items.length; i++) {
        var item = items[i];
        var amount = item.amount_cny || 0;
        var cat = item.category || '';
        if (item.name && item.name.indexOf('目的港港杂费') !== -1) {
            setOtherFee('目的港港杂费', amount);
        } else if ((item.name && item.name.indexOf('港杂费') !== -1) || cat.indexOf('港杂费') !== -1) {
            fd.portMisc.fee = amount;
            var boxCountForFee = primary.cost.box_count || 1;
            fd.portMisc.perBoxFee = Math.round(amount / boxCountForFee * 100) / 100;
        } else if ((item.name && item.name.indexOf('陆运费') !== -1) || cat.indexOf('拖车费') !== -1) {
            fd.land.baseFreight = amount;
            var landBoxCount = primary.cost.box_count || 1;
            fd.land.perBoxFee = Math.round(amount / landBoxCount * 100) / 100;
        } else if (item.name && item.name.indexOf('VGM') !== -1) {
            var vgmBoxes = primary.cost.box_count || 1;
            fd.seaManager.vgmFee = Math.round(amount / vgmBoxes * 100) / 100;
        } else if (item.name && item.name.indexOf('舱单') !== -1) {
            var manifestBoxes = primary.cost.box_count || 1;
            fd.seaManager.manifestFee = Math.round(amount / manifestBoxes * 100) / 100;
            fd.seaManager.manifestMode = 'custom';
            fd.seaManager.manifestCustom = fd.seaManager.manifestFee;
        } else if (item.name && item.name.indexOf('ICS2') !== -1) {
            fd.seaManager.ics2Enabled = true;
            fd.seaManager.ics2Fee = amount;
        } else if (item.name && item.name.indexOf('报关') !== -1) {
            setOtherFee('报关费', amount);
        } else if (item.name && item.name.indexOf('海运费') !== -1) {
            fd.ocean.fee = amount;
            if (item.modified_by_user) oceanModified = true;
        } else if (item.name && item.name.indexOf('保险') !== -1) {
            setOtherFee('保险费', amount);
        }
    }
    // 如果有合约海运费信息，更新 ocean fee（仅在合约费率有效时覆盖）
    var oceanInfo = primary.oceanFreightInfo;
    if (oceanInfo && oceanInfo.rate_cny && oceanInfo.rate_cny > 0 && !oceanModified) {
        var contractOceanFee = oceanInfo.rate_cny * (primary.cost.box_count || 1);
        if (Math.abs(contractOceanFee - fd.ocean.fee) > 1) {
            fd.ocean.fee = contractOceanFee;
        }
        fd.ocean.contractRate = oceanInfo.rate_usd;
        fd.ocean.contractCarrier = oceanInfo.carrier;
        fd.ocean.source = oceanInfo.is_valid ? 'contract_valid' : 'contract_expired';
    }
    fd._fromRecommendation = true;
    if (!store.feeConfirmed) {
        fetchLandFreightFromRoute(primary.factory, primary.departurePort, fd.land.transportMode || 'direct');
    }
    console.log('[FeeData] 已从推荐结果更新:', fd);
}
