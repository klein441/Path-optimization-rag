/**
 * 表单提交 / 重新优化
 */
import { store } from './state.js';
import { apiRecommend } from './api.js';
import { calculateAllFees, applyResultToFeeData } from './fees.js';

function buildPayload() {
    const form = store.form;
    const productTypes = form.productTypes.slice();
    const boxTypes = form.boxTypes.slice();
    const weightPerBox = parseFloat(form.weightPerBox) || 15;
    const totalBoxes = parseInt(form.boxes) || 0;
    const totalWeight = Math.round(weightPerBox * totalBoxes);

    return {
        customer: form.customer,
        orderNumber: form.orderNumber,
        productType: productTypes.join(','),
        productTypes: productTypes,
        productSizes: Object.assign({}, form.productSizes),
        boxTypes: boxTypes,
        boxTypeCounts: Object.assign({}, form.boxTypeCounts),
        destCountry: form.destCountry,
        destPort: form.destPort,
        gloveQty: parseInt(form.gloveQty) || 0,
        boxCount: totalBoxes,
        weight: totalWeight,
        volume: parseFloat(form.volume) || 0,
        cargoReady: form.cargoReady,
        shipSchedule: form.shipSchedule,
        transportPref: form.transportPref,
        tradePref: form.tradePref,
        remarks: form.remarks,
        costInfo: {
            total: calculateAllFees(),
            details: store.feeData
        }
    };
}

function applySuccess(result, payload) {
    store.lastSubmitPayload = payload;
    applyResultToFeeData(result.data);
    store.results.status = 'success';
    store.results.data = result.data;
    store.results.primary = result.data.primary;
    store.results.alternatives = result.data.alternatives || [];
    store.results.allCandidates = result.data.allCandidates || [];
    store.metaText = '推荐方案';
}

// ===== 智能路径推荐提交 =====
export async function handleSubmit() {
    const form = store.form;
    const productTypes = form.productTypes.slice();
    const boxTypes = form.boxTypes.slice();

    if (productTypes.length === 0) {
        alert('请选择至少一种产品类型');
        return;
    }
    if (boxTypes.length === 0) {
        alert('请选择至少一种集装箱箱型');
        return;
    }
    if (!form.destCountry) {
        alert('请选择运抵国 / 地区');
        return;
    }
    if (!form.destPort) {
        alert('请选择或填写终到港');
        return;
    }
    if (!form.cargoReady || !form.shipSchedule) {
        alert('请填写日期信息');
        return;
    }

    const payload = buildPayload();

    store.feeConfirmed = false;
    store.feeModified = {};
    store.submitting = true;
    store.results.status = 'loading';
    store.metaText = '正在分析...';

    try {
        const result = await apiRecommend(payload);
        if (result.success) {
            applySuccess(result, payload);
        } else {
            throw new Error(result.error || '推荐生成失败');
        }
    } catch (e) {
        console.error('[API] 错误:', e);
        store.results.status = 'error';
        store.metaText = '错误';
        store.results.errorMsg = '获取推荐方案失败，请确认后端服务已启动（http://localhost:5000）';
    } finally {
        store.submitting = false;
    }
}

// ===== 重新优化（使用修改后的费用数据重新提交）=====
export async function reOptimize() {
    if (!store.lastSubmitPayload) {
        alert('请先提交一次查询');
        return;
    }

    const fd = store.feeData;
    const mods = store.feeModified || {};
    const hasMods = Object.keys(mods).length > 0;
    var modifiedCostItems = [];
    var totalCny = 0;

    function pushItem(name, amount, isOther) {
        // 仅将用户实际修改过的费用项发给后端重新优化；未修改时不覆盖各路线原计算值
        if (!hasMods || mods[name] === true || (isOther && mods.__other__ === true)) {
            if (amount > 0 || name.indexOf('费') !== -1) {
                modifiedCostItems.push({ name: name, amount_cny: amount });
            }
        }
        totalCny += amount;
    }

    // 陆运费
    pushItem('陆运费', fd.land.baseFreight);
    if (fd.land.tollEnabled && fd.land.tollFee > 0) pushItem('高速费', fd.land.tollFee);
    if (fd.land.insideLoadEnabled && fd.land.insideLoadFee > 0) pushItem('内装费', fd.land.insideLoadFee);

    // 海管家费用
    pushItem('舱单费', fd.seaManager.manifestFee);
    pushItem('VGM费', fd.seaManager.vgmFee);
    if (fd.seaManager.ics2Enabled && fd.seaManager.ics2Fee > 0) pushItem('ICS2费', fd.seaManager.ics2Fee);

    // 港杂费
    pushItem('港杂费', fd.portMisc.fee);

    // 海运费
    pushItem('海运费', fd.ocean.fee);

    // 其他费用
    for (var k = 0; k < fd.other.length; k++) {
        var o = fd.other[k];
        if (o.amount > 0 || (o.name && o.name.trim() !== '')) {
            pushItem(o.name || '其他费用', o.amount, true);
        }
    }

    // 重置推荐标记，允许下次结果返回时用新数据更新 feeData
    fd._fromRecommendation = false;

    var payload = JSON.parse(JSON.stringify(store.lastSubmitPayload));
    payload.costInfo = {
        total: totalCny,
        details: fd,
        modifiedCostItems: modifiedCostItems
    };

    store.feeConfirmed = false;
    store.submitting = true;
    store.results.status = 'loading';
    store.metaText = '正在分析...';

    try {
        var result = await apiRecommend(payload);
        if (result.success) {
            applySuccess(result, payload);
        } else {
            throw new Error(result.error || '推荐生成失败');
        }
    } catch (e) {
        console.error('[API] 错误:', e);
        store.results.status = 'error';
        store.metaText = '错误';
        store.results.errorMsg = '重新优化失败，请确认后端服务已启动（http://localhost:5000）';
    } finally {
        store.submitting = false;
    }
}