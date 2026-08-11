/**
 * 费用计算与费用面板逻辑
 */
import { TRANSPORT_MODE_FREIGHT } from './constants.js';
import { store } from './state.js';
import { getOriginPortByProvince } from './utils.js';
import { apiEstimateToll, fetchLandFreightFromRoute } from './api.js';

export function getSeaManagerTotal() {
    const sm = store.feeData.seaManager;
    return sm.manifestFee + sm.vgmFee + sm.ics2Fee;
}

export function getOtherTotal() {
    return store.feeData.other.reduce((sum, o) => sum + (parseFloat(o.amount) || 0), 0);
}

export function calculateAllFees() {
    const fd = store.feeData;
    const landTotal = fd.land.baseFreight + fd.land.tollFee + fd.land.insideLoadFee;
    return landTotal + getSeaManagerTotal() + fd.portMisc.fee + fd.ocean.fee + getOtherTotal();
}

// ===== 陆运费初始化（根据工厂省份和运输方式自动推荐）=====
// factoryName 和 originPort 可选：传入时从各路线报价卡实时查询陆运费
export function initLandFees(province, mode, factoryName, originPort) {
    const fd = store.feeData;
    fd.land.factoryProvince = province || '';
    if (factoryName) fd.land.factoryName = factoryName;
    if (originPort) fd.land.originPort = originPort;
    mode = mode || 'direct';
    const conf = TRANSPORT_MODE_FREIGHT[mode];
    if (!conf) return;
    fd.land.transportMode = mode;
    fd.land.baseFreight = conf.baseFreight;
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
                ', 箱数=' + boxCount + ', 高速费=¥' + toll + ' (来源: ' + (result.data.source || 'llm') + ')');
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
    var items = primary.cost.items;
    const fd = store.feeData;
    var oceanModified = false; // 海运费是否来自用户手动修改（重新优化时保留用户确认值）
    for (var i = 0; i < items.length; i++) {
        var item = items[i];
        var amount = item.amount_cny || 0;
        var cat = item.category || '';
        if ((item.name && item.name.indexOf('港杂费') !== -1) || cat.indexOf('港杂费') !== -1) {
            fd.portMisc.fee = amount;
        } else if ((item.name && item.name.indexOf('陆运费') !== -1) || cat.indexOf('拖车费') !== -1) {
            fd.land.baseFreight = amount;
        } else if (item.name && item.name.indexOf('VGM') !== -1) {
            fd.seaManager.vgmFee = amount;
        } else if (item.name && item.name.indexOf('舱单') !== -1) {
            fd.seaManager.manifestFee = amount;
            fd.seaManager.manifestMode = 'custom';
            fd.seaManager.manifestCustom = amount;
        } else if (item.name && item.name.indexOf('ICS2') !== -1) {
            fd.seaManager.ics2Enabled = true;
            fd.seaManager.ics2Fee = amount;
        } else if (item.name && item.name.indexOf('报关') !== -1) {
            fd.other = fd.other || [];
            var found = false;
            for (var j = 0; j < fd.other.length; j++) {
                if (fd.other[j].name === '报关费') { fd.other[j].amount = amount; found = true; break; }
            }
            if (!found) fd.other.push({ name: '报关费', amount: amount });
        } else if (item.name && item.name.indexOf('海运费') !== -1) {
            fd.ocean.fee = amount;
            if (item.modified_by_user) oceanModified = true;
        } else if (item.name && item.name.indexOf('保险') !== -1) {
            fd.other = fd.other || [];
            var found2 = false;
            for (var k = 0; k < fd.other.length; k++) {
                if (fd.other[k].name === '保险费') { fd.other[k].amount = amount; found2 = true; break; }
            }
            if (!found2) fd.other.push({ name: '保险费', amount: amount });
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
    store.feeModified = {}; // 新结果回填后清除修改标记
    console.log('[FeeData] 已从推荐结果更新:', fd);
}