/**
 * 表单提交 / 推荐
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
        gloveUnit: form.gloveUnit || '千支',
        boxCount: totalBoxes,
        weight: totalWeight,
        volume: parseFloat(form.volume) || 0,
        cargoReady: form.cargoReady,
        requiredArrival: form.requiredArrival || '',
        urgent: Boolean(form.urgent),
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
    applyResultToFeeData(result.data);
    if (result.data && result.data.cannotMeetArrival) {
        alert(result.data.riskWarning || '所有方案均无法按客户约定时间到货，请调整到货时间或选择更早船期。');
    }
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
    if (!form.cargoReady) {
        alert('请填写预计货好时间');
        return;
    }

    const payload = buildPayload();

    store.feeConfirmed = false;
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

