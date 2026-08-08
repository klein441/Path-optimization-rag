/**
 * 物流运输路径智能优化系统 — 前端交互逻辑
 */

// ===== API 配置 =====
const API_BASE = 'http://localhost:5000';

// ===== 运输方式推荐陆运费 =====
const TRANSPORT_MODE_FREIGHT = {
    direct:     { label: '直拖',   baseFreight: 500, hasToll: false },
    seaRail:    { label: '海铁',   baseFreight: 300, hasToll: false },
    factorySelf:{ label: '工厂自运', baseFreight: 200, hasToll: true },
    landToWater:{ label: '陆改水', baseFreight: 400, hasToll: false },
};

// ===== 全局费用数据 =====
let feeData = {
    land: { transportMode: 'direct', baseFreight: 500, tollEnabled: false, tollFee: 0, insideLoadEnabled: false, insideLoadFee: 0, factoryProvince: '' },
    seaManager: { manifestFee: 55, manifestCustom: 0, manifestMode: 'default', vgmFee: 5, ics2Enabled: false, ics2Fee: 0 },
    portMisc: { fee: 320 },
    ocean: { fee: 2500 },
    other: [] // [{name, amount}]
};

// 存储上次提交的表单数据，用于重新优化
let lastSubmitPayload = null;

// ===== 日期工具 =====
function formatDate(d) {
    if (!d) return '';
    return d.toISOString().split('T')[0];
}

function initDateDefaults() {
    const today = new Date();
    const in7Days = new Date(today.getTime() + 7 * 24 * 60 * 60 * 1000);
    const in14Days = new Date(today.getTime() + 14 * 24 * 60 * 60 * 1000);

    const cargoReadyEl = document.getElementById('cargoReady');
    const shipScheduleEl = document.getElementById('shipSchedule');

    if (cargoReadyEl) cargoReadyEl.value = formatDate(in7Days);
    if (shipScheduleEl) shipScheduleEl.value = formatDate(in14Days);
}

// ===== DOM 元素 =====
const form = document.getElementById('logisticsForm');
const submitBtn = document.getElementById('submitBtn');
const resultBody = document.getElementById('resultBody');
const resultMeta = document.getElementById('resultMeta');

// ===== 初始化 =====
document.addEventListener('DOMContentLoaded', () => {
    initDateDefaults();
    setupFormSubmit();
    setupAdvancedToggle();
    loadCountries();
    setupMultiSelects();
    hookBoxTypeChange();
    hookWeightPerBox();
    setupFeeCalculations();
    initLandFees('', 'direct');
    updateGrandTotal();
});

// ===== 多选组件 =====
function setupMultiSelects() {
    document.querySelectorAll('.multi-select').forEach(ms => {
        const trigger = ms.querySelector('.multi-select-trigger');
        const dropdown = ms.querySelector('.multi-select-dropdown');
        const placeholder = ms.querySelector('.multi-select-placeholder');
        const tagsContainer = ms.querySelector('.multi-select-tags');

        trigger.addEventListener('click', (e) => {
            e.stopPropagation();
            document.querySelectorAll('.multi-select.open').forEach(other => {
                if (other !== ms) other.classList.remove('open');
            });
            ms.classList.toggle('open');
        });

        dropdown.querySelectorAll('input[type="checkbox"]').forEach(cb => {
            cb.addEventListener('change', () => {
                updateMultiSelectDisplay(ms);
            });
        });
    });

    document.addEventListener('click', () => {
        document.querySelectorAll('.multi-select.open').forEach(ms => {
            ms.classList.remove('open');
        });
    });
}

function updateMultiSelectDisplay(ms) {
    const placeholder = ms.querySelector('.multi-select-placeholder');
    const tagsContainer = ms.querySelector('.multi-select-tags');
    const checkboxes = ms.querySelectorAll('input[type="checkbox"]');

    if (tagsContainer) tagsContainer.remove();

    const selected = [];
    checkboxes.forEach(cb => {
        const option = cb.closest('.ms-option');
        if (cb.checked) {
            option.classList.add('selected');
            selected.push({ value: cb.value, label: cb.nextElementSibling?.textContent?.trim() || cb.value });
        } else {
            option.classList.remove('selected');
        }
    });

    if (selected.length > 0) {
        if (placeholder) placeholder.style.display = 'none';
        const newTags = document.createElement('span');
        newTags.className = 'multi-select-tags';
        selected.forEach(s => {
            const tag = document.createElement('span');
            tag.className = 'ms-tag';
            const shortLabel = s.label.split('（')[0];
            tag.innerHTML = `${shortLabel}<span class="ms-tag-x" data-value="${s.value}">×</span>`;
            newTags.appendChild(tag);
        });
        ms.querySelector('.multi-select-trigger').insertBefore(newTags, ms.querySelector('.ms-arrow'));
    } else {
        if (placeholder) placeholder.style.display = '';
    }

    ms.querySelectorAll('.ms-tag-x').forEach(x => {
        x.addEventListener('click', (e) => {
            e.stopPropagation();
            const val = x.dataset.value;
            const cb = ms.querySelector(`input[value="${val}"]`);
            if (cb) {
                cb.checked = false;
                updateMultiSelectDisplay(ms);
            }
        });
    });
}

function getMultiSelectValues(msId) {
    const ms = document.getElementById(msId);
    if (!ms) return [];
    const values = [];
    ms.querySelectorAll('input[type="checkbox"]:checked').forEach(cb => {
        values.push(cb.value);
    });
    return values;
}

// ===== 集装箱箱型固定体积（m³）=====
const BOX_VOLUMES = {
    "20GP": 33.1, "40GP": 67.5, "40HQ": 76.0, "45HQ": 85.0,
    "20RF": 33.1, "40RF": 67.5, "20OT": 33.1, "40OT": 67.5,
    "20FR": 33.1, "40FR": 67.5,
};

// 跟踪各箱型数量
let boxTypeCounts = {};  // { "40HQ": 5, "20GP": 3 }

function updateBoxTypeQuantities() {
    const selected = getMultiSelectValues('boxTypeMulti');
    const container = document.getElementById('boxTypeQuantities');
    const group = document.getElementById('boxTypeQuantitiesGroup');

    if (!container || !group) return;

    // 保留已有数量
    const newCounts = {};
    selected.forEach(bt => {
        newCounts[bt] = boxTypeCounts[bt] || 1;
    });
    boxTypeCounts = newCounts;

    if (selected.length === 0) {
        group.style.display = 'none';
        document.getElementById('boxes').value = 1;
        document.getElementById('volume').value = 0;
        document.getElementById('volumeHint').textContent = '请先选择集装箱箱型';
        document.getElementById('weight').value = 15;
        return;
    }

    group.style.display = '';

    let html = '';
    selected.forEach(bt => {
        const vol = BOX_VOLUMES[bt] || 0;
        const qty = boxTypeCounts[bt] || 1;
        const subtotal = (vol * qty).toFixed(1);
        html += `
            <div class="box-qty-row">
                <span class="box-qty-type">${bt}</span>
                <span class="box-qty-volume">${vol} m³/箱</span>
                <span class="box-qty-label">数量:</span>
                <input type="number" class="box-qty-input" data-box-type="${bt}" value="${qty}" min="1" max="9999" step="1">
                <span class="box-qty-subtotal">${subtotal} m³</span>
            </div>`;
    });

    // 汇总行
    const totalBoxes = Object.values(boxTypeCounts).reduce((s, n) => s + n, 0);
    const totalVolume = selected.reduce((sum, bt) => sum + (BOX_VOLUMES[bt] || 0) * (boxTypeCounts[bt] || 1), 0);

    html += `
        <div class="box-qty-summary">
            装箱总数: <span>${totalBoxes} 箱</span>
            总体积合计: <span>${totalVolume.toFixed(1)} m³</span>
        </div>`;

    container.innerHTML = html;

    // 更新主表单
    document.getElementById('boxes').value = totalBoxes;
    document.getElementById('volume').value = totalVolume.toFixed(1);
    document.getElementById('volumeHint').textContent =
        selected.map(bt => `${boxTypeCounts[bt] || 1}×${bt}(${BOX_VOLUMES[bt]}m³)`).join(' + ') + ` = ${totalVolume.toFixed(1)} m³`;

    // 总重量 = 单箱平均重量 × 装箱总数
    const weightPerBox = parseFloat(document.getElementById('weightPerBox').value) || 15;
    document.getElementById('weight').value = Math.round(weightPerBox * totalBoxes);

    // 绑定数量输入事件
    container.querySelectorAll('.box-qty-input').forEach(input => {
        input.addEventListener('input', () => {
            const bt = input.dataset.boxType;
            const n = parseInt(input.value) || 1;
            boxTypeCounts[bt] = Math.max(1, n);
            updateBoxTypeQuantities();
        });
    });
}

// 在箱型多选变化时触发
function hookBoxTypeChange() {
    const ms = document.getElementById('boxTypeMulti');
    if (!ms) return;
    ms.querySelectorAll('input[type="checkbox"]').forEach(cb => {
        // 避免重复绑定
        if (cb.dataset.hooked) return;
        cb.dataset.hooked = '1';
        cb.addEventListener('change', () => {
            updateMultiSelectDisplay(ms);
            updateBoxTypeQuantities();
        });
    });
}

// 单箱重量变化时更新总重量
function hookWeightPerBox() {
    const wpb = document.getElementById('weightPerBox');
    if (!wpb || wpb.dataset.hooked) return;
    wpb.dataset.hooked = '1';
    wpb.addEventListener('input', () => {
        const totalBoxes = parseInt(document.getElementById('boxes').value) || 1;
        document.getElementById('weight').value = Math.round((parseFloat(wpb.value) || 15) * totalBoxes);
    });
}

// ===== 欧洲国家列表 =====
var EUROPEAN_COUNTRIES = [
    '德国', '荷兰', '英国', '法国', '意大利', '西班牙', '比利时', '波兰',
    '瑞典', '芬兰', '丹麦', '奥地利', '爱尔兰', '葡萄牙', '希腊',
    '捷克', '罗马尼亚', '匈牙利', '斯洛文尼亚', '爱沙尼亚', '立陶宛',
    '克罗地亚', '拉脱维亚', '保加利亚', '斯洛伐克', '卢森堡', '马耳他',
    '塞浦路斯', '挪威', '瑞士'
];

function isEuropeanCountry(country) {
    return EUROPEAN_COUNTRIES.indexOf(country) >= 0;
}

function autoEnableICS2ForEurope() {
    var destCountry = document.getElementById('destCountry')?.value || '';
    var ics2Toggle = document.getElementById('ics2Toggle');
    var ics2Fee = document.getElementById('ics2Fee');
    var ics2Unit = ics2Fee?.nextElementSibling;

    if (isEuropeanCountry(destCountry)) {
        if (ics2Toggle && !ics2Toggle.checked) {
            ics2Toggle.checked = true;
            feeData.seaManager.ics2Enabled = true;
            ics2Fee.style.display = '';
            if (ics2Unit) ics2Unit.style.display = '';
            ics2Fee.value = 70;
            feeData.seaManager.ics2Fee = 70;
            updateGrandTotal();
        }
    }
}

// ===== 费用信息确认模态框 =====
function setupCostInfoModal() {
    const openBtn = document.getElementById('costInfoBtn');
    const modal = document.getElementById('costInfoModal');
    const closeBtn = document.getElementById('costInfoClose');
    const confirmBtn = document.getElementById('costInfoConfirm');

    openBtn.addEventListener('click', () => {
        modal.classList.add('open');
        autoEnableICS2ForEurope();
        fetchOceanFreightRate();
    });

    closeBtn.addEventListener('click', () => {
        modal.classList.remove('open');
    });

    modal.addEventListener('click', (e) => {
        if (e.target === modal) {
            modal.classList.remove('open');
        }
    });

    document.querySelectorAll('.fee-section-header').forEach(header => {
        header.addEventListener('click', () => {
            const section = header.closest('.fee-section');
            section.classList.toggle('open');
        });
    });

    // 海运费实时刷新
    const refreshBtn = document.getElementById('oceanRefreshBtn');
    if (refreshBtn) {
        refreshBtn.addEventListener('click', () => fetchOceanFreightRate());
    }
    const retryBtn = document.getElementById('oceanRetryBtn');
    if (retryBtn) {
        retryBtn.addEventListener('click', () => fetchOceanFreightRate());
    }

    confirmBtn.addEventListener('click', () => {
        const total = calculateAllFees();
        modal.classList.remove('open');

        let summaryBar = document.getElementById('feeSummaryBar');
        if (!summaryBar) {
            summaryBar = document.createElement('div');
            summaryBar.id = 'feeSummaryBar';
            summaryBar.className = 'fee-summary-bar';
            summaryBar.innerHTML = `
                <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><rect x="1" y="4" width="22" height="16" rx="2"/><line x1="1" y1="10" x2="23" y2="10"/><line x1="10" y1="4" x2="10" y2="20"/></svg>
                <span>已确认费用信息：陆运费 <b>¥${formatFee(feeData.land.baseFreight + feeData.land.tollFee + feeData.land.insideLoadFee)}</b> + 海管家 <b>¥${formatFee(getSeaManagerTotal())}</b> + 港杂 <b>¥${formatFee(feeData.portMisc.fee)}</b> + 海运 <b>¥${formatFee(feeData.ocean.fee)}</b> + 其他 <b>¥${formatFee(getOtherTotal())}</b></span>
                <svg class="chevron" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><polyline points="9 18 15 12 9 6"/></svg>
            `;
            summaryBar.addEventListener('click', () => {
                summaryBar.classList.toggle('open');
                const detailList = document.getElementById('feeDetailList');
                if (detailList) {
                    detailList.classList.toggle('open');
                } else {
                    renderFeeDetailList();
                }
            });

            const detailList = document.createElement('div');
            detailList.id = 'feeDetailList';
            detailList.className = 'fee-detail-list';
            renderFeeDetailList();

            const existingBar = document.getElementById('feeSummaryBar');
            if (existingBar && existingBar.parentNode) {
                existingBar.parentNode.insertBefore(summaryBar, existingBar.nextSibling);
                if (detailList.style.display === 'none') detailList.classList.remove('open');
            }
        } else {
            summaryBar.classList.add('open');
            const detailList = document.getElementById('feeDetailList');
            if (detailList) {
                detailList.classList.add('open');
                renderFeeDetailList();
            }
        }

        resultMeta.textContent = '推荐方案';
        showNotification('费用信息已确认！点击"智能路径推荐"获取方案。');
    });
}

function showNotification(msg) {
    resultMeta.textContent = '✓ ' + msg.split('！')[0];
    const originalMeta = resultMeta.textContent;
    setTimeout(() => {
        if (resultMeta.textContent === originalMeta) {
            resultMeta.textContent = '推荐方案';
        }
    }, 5000);
}

function renderFeeDetailList() {
    const detailList = document.getElementById('feeDetailList');
    if (!detailList) return;

    detailList.innerHTML = `
        <div class="fee-detail-group">
            <div class="fee-detail-group-title">陆运费（${TRANSPORT_MODE_FREIGHT[feeData.land.transportMode]?.label || feeData.land.transportMode}）</div>
            <div class="fee-detail-row"><span class="label">陆运费</span><span class="value">¥${formatFee(feeData.land.baseFreight)}</span></div>
            ${feeData.land.tollEnabled ? `<div class="fee-detail-row"><span class="label">高速费</span><span class="value">¥${formatFee(feeData.land.tollFee)}</span></div>` : ''}
            ${feeData.land.insideLoadEnabled ? `<div class="fee-detail-row"><span class="label">内装费</span><span class="value">¥${formatFee(feeData.land.insideLoadFee)}</span></div>` : ''}
        </div>
        <div class="fee-detail-group">
            <div class="fee-detail-group-title">海管家费用</div>
            <div class="fee-detail-row"><span class="label">舱单费</span><span class="value">¥${formatFee(feeData.seaManager.manifestFee)}</span></div>
            <div class="fee-detail-row"><span class="label">VGM费</span><span class="value">¥${formatFee(feeData.seaManager.vgmFee)}</span></div>
            ${feeData.seaManager.ics2Enabled ? `<div class="fee-detail-row"><span class="label">ICS2费</span><span class="value">¥${formatFee(feeData.seaManager.ics2Fee)}</span></div>` : ''}
        </div>
        <div class="fee-detail-group">
            <div class="fee-detail-group-title">港杂费</div>
            <div class="fee-detail-row"><span class="label">港杂费合计</span><span class="value">¥${formatFee(feeData.portMisc.fee)}</span></div>
        </div>
        <div class="fee-detail-group">
            <div class="fee-detail-group-title">海运费</div>
            <div class="fee-detail-row"><span class="label">海运费合计</span><span class="value">¥${formatFee(feeData.ocean.fee)}</span></div>
        </div>
        ${feeData.other.length > 0 ? `
        <div class="fee-detail-group">
            <div class="fee-detail-group-title">其他费用</div>
            ${feeData.other.map(o => `<div class="fee-detail-row"><span class="label">${o.name || '未命名'}</span><span class="value">¥${formatFee(o.amount)}</span></div>`).join('')}
        </div>` : ''}
        <div class="fee-detail-group" style="margin-top:0.5rem;border-top:1px solid var(--rule);padding-top:0.5rem">
            <div class="fee-detail-group-title">费用总计</div>
            <div class="fee-detail-row"><span class="label">合计</span><span class="value" style="color:var(--accent)">¥${formatFee(calculateAllFees())}</span></div>
        </div>
    `;
}

// ===== 费用计算逻辑 =====
function setupFeeCalculations() {
    // 陆运费 - 运输方式切换
    const transportMode = document.getElementById('transportModeSelect');
    const baseFreightInput = document.getElementById('landBaseFreight');
    const tollFee = document.getElementById('landTollFee');
    const insideToggle = document.getElementById('insideLoadToggle');
    const insideFee = document.getElementById('insideLoadFee');
    const insideUnit = insideFee?.nextElementSibling;

    transportMode.addEventListener('change', () => {
        initLandFees(feeData.land.factoryProvince, transportMode.value,
                     feeData.land.factoryName || '', feeData.land.originPort || '');
        // 工厂自运时智能计算高速费
        if (transportMode.value === 'factorySelf') {
            calculateTollFee();
        }
    });

    baseFreightInput.addEventListener('input', () => {
        feeData.land.baseFreight = parseFloat(baseFreightInput.value) || 0;
        updateGrandTotal();
    });

    // 高速费 toggle + input
    const tollToggle = document.getElementById('landTollToggle');
    tollToggle.addEventListener('change', () => {
        feeData.land.tollEnabled = tollToggle.checked;
        if (tollToggle.checked) {
            feeData.land.tollFee = parseFloat(tollFee.value) || 0;
        } else {
            feeData.land.tollFee = 0;
        }
        updateGrandTotal();
    });

    tollFee.addEventListener('input', () => {
        feeData.land.tollFee = parseFloat(tollFee.value) || 0;
        if (!tollToggle.checked && feeData.land.tollFee > 0) {
            tollToggle.checked = true;
            feeData.land.tollEnabled = true;
        }
        updateGrandTotal();
    });

    // 内装费 toggle + input
    insideToggle.addEventListener('change', () => {
        feeData.land.insideLoadEnabled = insideToggle.checked;
        insideFee.style.display = insideToggle.checked ? '' : 'none';
        if (insideUnit) insideUnit.style.display = insideToggle.checked ? '' : 'none';
        if (insideToggle.checked) {
            feeData.land.insideLoadFee = parseFloat(insideFee.value) || 0;
        } else {
            feeData.land.insideLoadFee = 0;
        }
        updateGrandTotal();
    });

    insideFee.addEventListener('input', () => {
        feeData.land.insideLoadFee = parseFloat(insideFee.value) || 0;
        updateGrandTotal();
    });

    // 海管家 - 舱单费
    const manifestSelect = document.getElementById('manifestFeeSelect');
    const manifestCustom = document.getElementById('manifestFeeCustom');

    manifestSelect.addEventListener('change', () => {
        const val = manifestSelect.value;
        if (val === 'custom') {
            manifestCustom.style.display = '';
            feeData.seaManager.manifestMode = 'custom';
            feeData.seaManager.manifestFee = parseFloat(manifestCustom.value) || 0;
        } else {
            manifestCustom.style.display = 'none';
            feeData.seaManager.manifestMode = val;
            feeData.seaManager.manifestFee = parseFloat(val);
        }
        updateGrandTotal();
    });

    manifestCustom.addEventListener('input', () => {
        feeData.seaManager.manifestFee = parseFloat(manifestCustom.value) || 0;
        updateGrandTotal();
    });

    // 海管家 - VGM费
    const vgmFee = document.getElementById('vgmFee');
    vgmFee.addEventListener('input', () => {
        feeData.seaManager.vgmFee = parseFloat(vgmFee.value) || 0;
        updateGrandTotal();
    });

    // 海管家 - ICS2费
    const ics2Toggle = document.getElementById('ics2Toggle');
    const ics2Fee = document.getElementById('ics2Fee');
    const ics2Unit = ics2Fee?.nextElementSibling;

    ics2Toggle.addEventListener('change', () => {
        feeData.seaManager.ics2Enabled = ics2Toggle.checked;
        ics2Fee.style.display = ics2Toggle.checked ? '' : 'none';
        if (ics2Unit) ics2Unit.style.display = ics2Toggle.checked ? '' : 'none';
        if (!ics2Toggle.checked) {
            ics2Fee.value = 0;
            feeData.seaManager.ics2Fee = 0;
        }
        updateGrandTotal();
    });

    ics2Fee.addEventListener('input', () => {
        feeData.seaManager.ics2Fee = parseFloat(ics2Fee.value) || 0;
        updateGrandTotal();
    });

    // 港杂费
    const portMiscFee = document.getElementById('portMiscFee');
    portMiscFee.addEventListener('input', () => {
        feeData.portMisc.fee = parseFloat(portMiscFee.value) || 0;
        updateGrandTotal();
    });

    // 海运费
    const oceanFee = document.getElementById('oceanFee');
    oceanFee.addEventListener('input', () => {
        feeData.ocean.fee = parseFloat(oceanFee.value) || 0;
        updateGrandTotal();
    });
}

// ===== 陆运费初始化（根据工厂省份和运输方式自动推荐）=====
// factoryName 和 originPort 可选：传入时从各路线报价卡实时查询陆运费
function initLandFees(province, mode, factoryName, originPort) {
    feeData.land.factoryProvince = province || '';
    if (factoryName) feeData.land.factoryName = factoryName;
    if (originPort) feeData.land.originPort = originPort;
    const transportMode = document.getElementById('transportModeSelect');
    const baseFreightInput = document.getElementById('landBaseFreight');
    const tollItem = document.getElementById('tollFeeItem');
    const insideItem = document.getElementById('insideLoadItem');
    const tollToggle = document.getElementById('landTollToggle');
    const tollFee = document.getElementById('landTollFee');
    const insideToggle = document.getElementById('insideLoadToggle');
    const insideFee = document.getElementById('insideLoadFee');
    const insideUnit = insideFee?.nextElementSibling;

    function isJiangxiOrAnqing(prov) {
        return prov === '江西' || prov === '安徽';
    }

    mode = mode || 'direct';
    const conf = TRANSPORT_MODE_FREIGHT[mode];
    if (!conf) return;

    // 设置运输方式
    transportMode.value = mode;
    feeData.land.transportMode = mode;

    // 推荐陆运费：优先从各路线报价卡实时查询，fallback 到默认值
    feeData.land.baseFreight = conf.baseFreight;
    baseFreightInput.value = conf.baseFreight;

    if (factoryName && originPort) {
        fetchLandFreightFromRoute(factoryName, originPort, mode);
    }

    // 高速费（仅工厂自运，智能计算）
    if (conf.hasToll) {
        tollItem.style.display = '';
        tollToggle.checked = true;
        feeData.land.tollEnabled = true;
        // 如果已知工厂省份，智能计算高速费；否则用默认值
        if (province) {
            calculateTollFee();
        } else {
            tollFee.value = 50;
            feeData.land.tollFee = 50;
        }
    } else {
        tollItem.style.display = 'none';
        tollToggle.checked = false;
        tollFee.value = 50;
        feeData.land.tollEnabled = false;
        feeData.land.tollFee = 0;
    }

    // 内装费（仅江西/安庆基地）
    if (isJiangxiOrAnqing(province)) {
        insideItem.style.display = '';
        insideToggle.checked = false;
        feeData.land.insideLoadEnabled = false;
        insideFee.style.display = 'none';
        insideFee.value = 100;
        if (insideUnit) insideUnit.style.display = 'none';
        feeData.land.insideLoadFee = 0;
    } else {
        insideItem.style.display = 'none';
        insideToggle.checked = false;
        feeData.land.insideLoadEnabled = false;
        insideFee.value = 100;
        feeData.land.insideLoadFee = 0;
    }

    updateGrandTotal();
}

// 工厂自运高速费 LLM 智能计算（调用后端 DeepSeek LLM）
async function calculateTollFee() {
    var province = feeData.land.factoryProvince || '';
    var boxCount = parseInt(document.getElementById('boxes')?.value) || 1;
    var boxTypes = getMultiSelectValues('boxTypeMulti');
    if (boxTypes.length === 0) boxTypes = ['40HQ'];
    var weight = parseFloat(document.getElementById('weight')?.value) || 0;
    var volume = parseFloat(document.getElementById('volume')?.value) || 0;

    // 获取始发港（从弹窗中的推荐航线信息）
    var originPort = document.getElementById('routeInfoOrigin')?.textContent || '';
    if (originPort === '—' || !originPort) {
        // 回退：根据省份推断
        var portMap = { '山东': '青岛/QINGDAO', '安徽': '上海/SHANGHAI', '江西': '上海/SHANGHAI', '江苏': '上海/SHANGHAI', '上海': '上海/SHANGHAI' };
        originPort = portMap[province] || '上海/SHANGHAI';
    }

    if (!province) {
        console.warn('[高速费] 缺少工厂省份信息，使用默认值50');
        applyTollFee(50);
        return;
    }

    // 显示加载状态
    var tollFeeInput = document.getElementById('landTollFee');
    if (tollFeeInput) tollFeeInput.placeholder = 'LLM 计算中...';

    try {
        var resp = await fetch(API_BASE + '/api/estimate-toll', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                province: province,
                originPort: originPort,
                boxCount: boxCount,
                boxTypes: boxTypes,
                weight: weight,
                volume: volume,
            }),
        });

        var result = await resp.json();
        if (result.success && result.data && result.data.tollFee > 0) {
            var toll = result.data.tollFee;
            applyTollFee(toll);
            console.log('[高速费] LLM计算完成: 省份=' + province + ', 港口=' + originPort +
                ', 箱数=' + boxCount + ', 高速费=¥' + toll + ' (来源: ' + (result.data.source || 'llm') + ')');
        } else {
            // 回退
            console.warn('[高速费] LLM返回异常，回退默认值:', result);
            applyTollFee(80);
        }
    } catch (e) {
        console.warn('[高速费] LLM调用失败，回退默认值:', e.message);
        applyTollFee(80);
    }

    if (tollFeeInput) tollFeeInput.placeholder = '高速费';
}

function applyTollFee(amount) {
    var tollFeeInput = document.getElementById('landTollFee');
    var tollToggle = document.getElementById('landTollToggle');
    if (tollFeeInput) {
        tollFeeInput.value = amount;
        feeData.land.tollFee = amount;
    }
    if (tollToggle) {
        tollToggle.checked = true;
        feeData.land.tollEnabled = true;
    }
    updateGrandTotal();
}

function getSeaManagerTotal() {
    return feeData.seaManager.manifestFee + feeData.seaManager.vgmFee + feeData.seaManager.ics2Fee;
}

function getOtherTotal() {
    return feeData.other.reduce((sum, o) => sum + (parseFloat(o.amount) || 0), 0);
}

function calculateAllFees() {
    const landTotal = feeData.land.baseFreight + feeData.land.tollFee + feeData.land.insideLoadFee;
    const seaManagerTotal = getSeaManagerTotal();
    const portMiscTotal = feeData.portMisc.fee;
    const oceanTotal = feeData.ocean.fee;
    const otherTotal = getOtherTotal();

    return landTotal + seaManagerTotal + portMiscTotal + oceanTotal + otherTotal;
}

function formatFee(val) {
    return (Math.round(val * 100) / 100).toFixed(2).replace(/\.?0+$/, '') || '0';
}

function updateGrandTotal() {
    const grandTotal = calculateAllFees();

    // 更新弹窗合计
    var gtEl = document.getElementById('grandTotal');
    if (gtEl) gtEl.textContent = '¥' + formatFee(grandTotal);

    // 更新各section汇总
    var lfs = document.getElementById('landFeeSummary');
    if (lfs) lfs.textContent = '¥' + formatFee(feeData.land.baseFreight + feeData.land.tollFee + feeData.land.insideLoadFee);
    var smfs = document.getElementById('seaManagerFeeSummary');
    if (smfs) smfs.textContent = '¥' + formatFee(getSeaManagerTotal());
    var pmfs = document.getElementById('portMiscFeeSummary');
    if (pmfs) pmfs.textContent = '¥' + formatFee(feeData.portMisc.fee);
    var ofs = document.getElementById('oceanFeeSummary');
    if (ofs) ofs.textContent = '¥' + formatFee(feeData.ocean.fee);
    var otfs = document.getElementById('otherFeeSummary');
    if (otfs) otfs.textContent = '¥' + formatFee(getOtherTotal());

    // 同步更新指标卡片的总费用
    var recCardCosts = document.querySelectorAll('.rec-card-value.mono');
    for (var i = 0; i < recCardCosts.length; i++) {
        var el = recCardCosts[i];
        if (el.textContent.indexOf('¥') === 0) {
            el.textContent = '¥' + grandTotal.toLocaleString();
            // 同时更新USD
            var sub = el.parentElement.querySelector('.rec-card-sub');
            if (sub) sub.textContent = '约 $' + Math.round(grandTotal / 7.2).toLocaleString() + ' USD';
        }
    }
}

function addOtherFeeRow() {
    const body = document.getElementById('otherFeeBody');
    const row = document.createElement('div');
    row.className = 'other-fee-row';
    row.innerHTML = `
        <input type="text" class="other-fee-name" placeholder="费用类型（如：熏蒸费、报关费等）">
        <input type="number" class="other-fee-amount" placeholder="金额" step="0.1" min="0">
        <button class="other-fee-remove" title="删除">
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/></svg>
        </button>
    `;
    body.insertBefore(row, body.querySelector('.other-fee-add'));

    const [nameInput, amountInput] = row.querySelectorAll('input');
    const removeBtn = row.querySelector('.other-fee-remove');

    nameInput.addEventListener('input', () => syncOtherFees());
    amountInput.addEventListener('input', () => syncOtherFees());
    removeBtn.addEventListener('click', () => {
        row.remove();
        syncOtherFees();
    });
}

function syncOtherFees() {
    const rows = document.querySelectorAll('#otherFeeBody .other-fee-row');
    feeData.other = [];
    rows.forEach(row => {
        const [nameInput, amountInput] = row.querySelectorAll('input');
        feeData.other.push({
            name: nameInput.value,
            amount: parseFloat(amountInput.value) || 0
        });
    });
    updateGrandTotal();
}

function updateOtherFeeTotal() {
    syncOtherFees();
}

// ===== 高级选项切换 =====
function setupAdvancedToggle() {
    const toggle = document.getElementById('advToggle');
    const section = document.getElementById('advSection');
    if (toggle && section) {
        toggle.addEventListener('click', () => {
            section.classList.toggle('open');
            toggle.classList.toggle('open');
        });
    }
}

// ===== 加载动态数据（工厂、国家列表等）=====
async function loadCountries() {
    try {
        const resp = await fetch(`${API_BASE}/api/logistics/countries`);
        const data = await resp.json();
        if (data.success && data.countries.length > 0) {
            console.log('[API] 加载了', data.count, '个运抵国');
        }
    } catch (e) {
        console.log('[API] 使用静态国家列表');
    }
}

// ===== 表单提交 =====
function setupFormSubmit() {
    form.addEventListener('submit', async (e) => {
        e.preventDefault();
        await handleSubmit();
    });
}

async function handleSubmit() {
    const productTypes = getMultiSelectValues('productTypeMulti');
    const boxTypes = getMultiSelectValues('boxTypeMulti');

    // 计算总重量：单箱平均重量 × 装箱总数
    const weightPerBox = parseFloat(document.getElementById('weightPerBox').value) || 15;
    const totalBoxes = parseInt(document.getElementById('boxes').value) || 0;
    const totalWeight = Math.round(weightPerBox * totalBoxes);

    const payload = {
        customer: document.getElementById('customer').value,
        orderNumber: document.getElementById('orderNumber')?.value || '',
        productType: productTypes.join(','),
        productTypes: productTypes,
        boxTypes: boxTypes,
        boxTypeCounts: boxTypeCounts,  // 各箱型数量，如 {"40HQ": 5, "20GP": 3}
        destCountry: document.getElementById('destCountry').value,
        boxCount: totalBoxes,
        weight: totalWeight,
        volume: parseFloat(document.getElementById('volume').value) || 0,
        cargoReady: document.getElementById('cargoReady').value,
        shipSchedule: document.getElementById('shipSchedule').value,
        transportPref: document.getElementById('transportPref').value,
        tradePref: document.getElementById('tradePref').value,
        remarks: document.getElementById('remarks')?.value || '',
        costInfo: {
            total: calculateAllFees(),
            details: feeData
        }
    };

    if (productTypes.length === 0) {
        alert('请选择至少一种产品类型');
        return;
    }
    if (boxTypes.length === 0) {
        alert('请选择至少一种集装箱箱型');
        return;
    }
    if (!payload.cargoReady || !payload.shipSchedule) {
        alert('请填写日期信息');
        return;
    }

    showLoading();
    submitBtn.disabled = true;

    try {
        const resp = await fetch(`${API_BASE}/api/logistics/recommend`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(payload),
        });

        if (!resp.ok) {
            throw new Error(`HTTP ${resp.status}`);
        }

        const result = await resp.json();
        if (result.success) {
            lastSubmitPayload = payload;
            renderResult(result.data);
            renderFeePanel(result.data);
            renderAlternativesAfterResults(result.data.alternatives || []);
        } else {
            throw new Error(result.error || '推荐生成失败');
        }
    } catch (e) {
        console.error('[API] 错误:', e);
        showError('获取推荐方案失败，请确认后端服务已启动（http://localhost:5000）');
    } finally {
        submitBtn.disabled = false;
    }
}

// ===== 加载状态 =====
function showLoading() {
    resultMeta.textContent = '正在分析...';
    resultBody.innerHTML = `
        <div class="loading-state">
            <div class="loading-spinner"></div>
            <h3>正在生成最优路径方案</h3>
            <p>系统正在分析工厂产能、港口资源、运输成本和时效...</p>
            <div class="loading-steps">
                <div class="loading-step active">
                    <span class="ls-dot"></span>
                    <span>匹配可用工厂</span>
                </div>
                <div class="loading-step">
                    <span class="ls-dot"></span>
                    <span>计算运输成本</span>
                </div>
                <div class="loading-step">
                    <span class="ls-dot"></span>
                    <span>评估时效路线</span>
                </div>
                <div class="loading-step">
                    <span class="ls-dot"></span>
                    <span>AI 智能推荐</span>
                </div>
            </div>
        </div>
    `;
}

// ===== 错误显示 =====
function showError(msg) {
    resultMeta.textContent = '错误';
    resultBody.innerHTML = `
        <div class="empty-state" style="min-height:400px">
            <div class="empty-icon" style="background:linear-gradient(135deg,rgba(220,38,38,0.08),rgba(220,38,38,0.05))">
                <svg viewBox="0 0 24 24" fill="none" stroke="#dc2626" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="10"/><line x1="15" y1="9" x2="9" y2="15"/><line x1="9" y1="9" x2="15" y2="15"/></svg>
            </div>
            <h3>请求失败</h3>
            <p>${msg}</p>
        </div>
    `;
}

// ===== 渲染推荐结果 =====
function renderResult(data) {
    resultMeta.textContent = '推荐方案';
    const primary = data.primary;
    const alternatives = data.alternatives || [];
    const reasoning = data.reasoning || '';
    const riskWarning = data.riskWarning || '';
    const optimizationSuggestion = data.optimizationSuggestion || '';

    resultBody.innerHTML = `
        <div class="results-container">
            ${renderRouteInfoBanner(primary)}
            ${renderRouteViz(primary)}
            <div id="feePanelPlaceholder"></div>
            ${renderSummaryBanner(primary, alternatives)}
            ${renderRecCards(primary)}
            ${renderCarrierAndShipping(primary)}
            ${renderTimeline(primary)}
            ${renderAIReasoning(reasoning, riskWarning, optimizationSuggestion, data)}
        </div>
    `;
}

// ===== 路线信息条（最上方） =====
function renderRouteInfoBanner(p) {
    var factory = p.factoryShort || p.factory || '—';
    var origin = p.departurePort || '—';
    var dest = p.destPort || '—';
    var tradeTerm = p.tradeTerm || 'FOB';
    var boxTypes = p.boxTypes || [p.boxType || '40HQ'];
    var boxTypeCounts = p.boxTypeCounts || {};
    var boxInfo = Object.keys(boxTypeCounts).length > 0
        ? Object.entries(boxTypeCounts).map(function(e) { return e[0] + '×' + e[1]; }).join(' + ')
        : (Array.isArray(boxTypes) ? boxTypes.join(' + ') : boxTypes);

    return '<div class="route-info-banner">' +
        '<div class="rib-item">' +
            '<div class="rib-label">🏭 发货工厂</div>' +
            '<div class="rib-value">' + factory + '</div>' +
        '</div>' +
        '<div class="rib-arrow">→</div>' +
        '<div class="rib-item">' +
            '<div class="rib-label">⚓ 始发港</div>' +
            '<div class="rib-value">' + origin + '</div>' +
        '</div>' +
        '<div class="rib-arrow">→</div>' +
        '<div class="rib-item">' +
            '<div class="rib-label">📍 终到港</div>' +
            '<div class="rib-value">' + dest + '</div>' +
        '</div>' +
        '<div class="rib-divider"></div>' +
        '<div class="rib-item">' +
            '<div class="rib-label">📋 贸易条款</div>' +
            '<div class="rib-value">' + tradeTerm + '</div>' +
        '</div>' +
        '<div class="rib-item">' +
            '<div class="rib-label">📦 箱型/数量</div>' +
            '<div class="rib-value">' + boxInfo + '</div>' +
        '</div>' +
        '</div>';
}

// ===== 路线可视化 =====
function renderRouteViz(p) {
    const factory = p.factoryShort || p.factory || '未知工厂';
    const origin = p.departurePort || '未指定';
    const dest = p.destPort || '未指定';
    const region = p.region || '';

    return `
        <div class="route-viz">
            <div class="route-viz-title">
                <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" style="width:14px;height:14px"><path d="M22 12h-4l-3 9L9 3l-3 9H2"/></svg>
                推荐路线
            </div>
            <div class="route-flow">
                <div class="route-node">
                    <div class="route-node-icon factory">
                        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M3 9l9-7 9 7v11a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z"/><polyline points="9 22 9 12 15 12 15 22"/></svg>
                    </div>
                    <div class="route-node-label">${factory}</div>
                    <div class="route-node-sub">${region}</div>
                </div>
                <div class="route-arrow">
                    <div class="ra-line"></div>
                    <div class="ra-label">陆运 ${p.inlandDays || '?'}天</div>
                </div>
                <div class="route-node">
                    <div class="route-node-icon port">
                        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M2 12h20"/><path d="M12 2a15.3 15.3 0 0 1 4 10 15.3 15.3 0 0 1-4 10 15.3 15.3 0 0 1-4-10 15.3 15.3 0 0 1 4-10z"/></svg>
                    </div>
                    <div class="route-node-label">${origin}</div>
                    <div class="route-node-sub">${p.tradeTerm || 'FOB'}</div>
                </div>
                <div class="route-arrow">
                    <div class="ra-line"></div>
                    <div class="ra-label">海运 ${p.oceanDays || '?'}天</div>
                </div>
                <div class="route-node">
                    <div class="route-node-icon dest">
                        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M21 10c0 7-9 13-9 13s-9-6-9-13a9 9 0 0 1 18 0z"/><circle cx="12" cy="10" r="3"/></svg>
                    </div>
                    <div class="route-node-label">${dest}</div>
                    <div class="route-node-sub">目的港</div>
                </div>
            </div>
        </div>
    `;
}

// ===== 摘要横幅 =====
function renderSummaryBanner(p, alts) {
    const totalDays = p.totalDays || 0;
    const score = p.score || 0;
    const items = [];

    if (p.needFDA) {
        items.push('FDA 合规');
    }
    if (p.isOverseas) {
        items.push('海外基地');
    }
    items.push(`综合评分 ${score}/100`);
    if (alts.length > 0) {
        items.push(`${alts.length} 个备选方案`);
    }

    return `
        <div class="summary-banner">
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M22 11.08V12a10 10 0 1 1-5.93-9.14"/><polyline points="22 4 12 14.01 9 11.01"/></svg>
            <span>预计 <b>${totalDays}</b> 天完成全部运输流程 · ${items.join(' · ')}</span>
        </div>
    `;
}

// ===== 关键指标卡片 =====
function renderRecCards(p) {
    const costCny = p.cost?.totalCny || 0;
    const costUsd = p.cost?.totalUsd || 0;
    const score = p.score || 0;

    return `
        <div class="rec-grid">
            <div class="rec-card">
                <div class="rec-card-label">
                    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><line x1="12" y1="1" x2="12" y2="23"/><path d="M17 5H9.5a3.5 3.5 0 0 0 0 7h5a3.5 3.5 0 0 1 0 7H6"/></svg>
                    预计总费用
                </div>
                <div class="rec-card-value mono">¥${costCny.toLocaleString()}</div>
                <div class="rec-card-sub">约 $${costUsd.toLocaleString()} USD</div>
            </div>
            <div class="rec-card">
                <div class="rec-card-label">
                    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="10"/><polyline points="12 6 12 12 16 14"/></svg>
                    运输周期
                </div>
                <div class="rec-card-value">${p.totalDays || '?'} 天</div>
                <div class="rec-card-sub">内陆 ${p.inlandDays || '?'}天 + 海运 ${p.oceanDays || '?'}天</div>
            </div>
            <div class="rec-card">
                <div class="rec-card-label">
                    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><polygon points="12 2 15.09 8.26 22 9.27 17 14.14 18.18 21.02 12 17.77 5.82 21.02 7 14.14 2 9.27 8.91 8.26 12 2"/></svg>
                    综合评分
                </div>
                <div class="rec-card-value">${score}<span style="font-size:0.8rem;color:var(--muted)">/100</span></div>
                <div class="rec-card-sub">${score >= 70 ? '优秀' : score >= 50 ? '良好' : '一般'}</div>
            </div>
        </div>
    `;
}

// ===== 费用明细 =====
function renderCostBreakdown(p) {
    const items = p.cost?.items || [];
    const calcDetails = p.cost?.calc_details || [];
    const boxCount = p.cost?.box_count || 1;
    const boxTypeCounts = p.cost?.box_type_counts || {};
    const boxTypesInfo = Object.entries(boxTypeCounts).length > 1
        ? Object.entries(boxTypeCounts).map(([bt, qty]) => `${bt}×${qty}`).join(' + ')
        : '';

    let rows = '';
    items.forEach((item, idx) => {
        rows += `
            <tr>
                <td>
                    <div class="cost-item-name">${idx + 1}. ${item.name}</div>
                    <div class="cost-item-basis">${item.basis || ''}</div>
                </td>
                <td class="cost-item-amount">
                    <div>¥${item.amount_cny?.toLocaleString() || item.amount?.toLocaleString() || '—'}</div>
                    <div class="cost-item-usd">$${item.amount_usd?.toLocaleString() || '—'}</div>
                </td>
            </tr>
        `;
    });

    const totalCny = p.cost?.totalCny || 0;
    const totalUsd = p.cost?.totalUsd || 0;

    let detailsHtml = '';
    if (calcDetails.length > 0) {
        detailsHtml = `
            <details class="calc-details">
                <summary>📐 查看费用计算过程（共 ${calcDetails.length} 项）</summary>
                <div class="calc-details-body">
                    <div class="calc-details-title">费用计算公式：</div>
                    ${calcDetails.map((d, i) => `<div class="calc-detail-item">${i + 1}. ${d}</div>`).join('')}
                    <div class="calc-details-note">
                        💡 以上费用基于历史真实费率动态计算，共使用 ${boxCount} 个集装箱
                    </div>
                </div>
            </details>
        `;
    }

    return `
        <div class="cost-section">
            <div class="cost-header">
                <h3>
                    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><rect x="1" y="4" width="22" height="16" rx="2" ry="2"/><line x1="1" y1="10" x2="23" y2="10"/></svg>
                    费用明细（共 ${items.length} 项 · ${boxCount} 个集装箱${boxTypesInfo ? ' · ' + boxTypesInfo : ''}）
                </h3>
            </div>
            <table class="cost-table">
                <thead>
                    <tr>
                        <th>费用项目</th>
                        <th>金额</th>
                    </tr>
                </thead>
                <tbody>
                    ${rows}
                </tbody>
                <tfoot>
                    <tr class="total">
                        <td>合计</td>
                        <td>
                            <div>¥${totalCny.toLocaleString()}</div>
                            <div class="cost-item-usd">$${totalUsd.toLocaleString()}</div>
                        </td>
                    </tr>
                </tfoot>
            </table>
            ${detailsHtml}
        </div>
    `;
}

// ===== 承运商和船公司 =====
function renderCarrierAndShipping(p) {
    const carrier = p.carrier || {};
    const shippingLine = p.shippingLine || {};
    const shippingLines = p.shippingLines || {};

    let carrierHtml = '';
    if (carrier.recommended) {
        const typeColor = carrier.type === '自有' ? 'var(--success, #16a34a)' : 'var(--accent, #B8860B)';
        const typeBg = carrier.type === '自有' ? 'rgba(22,163,74,0.1)' : 'rgba(184,134,11,0.1)';
        carrierHtml = `
            <div class="cs-card">
                <div class="cs-card-header">
                    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" style="width:16px;height:16px"><rect x="1" y="3" width="15" height="13"/><polygon points="16 8 20 8 23 11 23 16 16 16 16 8"/><circle cx="5.5" cy="18.5" r="2.5"/><circle cx="18.5" cy="18.5" r="2.5"/></svg>
                    承运商（车队）
                </div>
                <div class="cs-card-body">
                    <div class="cs-primary">
                        <span class="cs-name">${carrier.recommended}</span>
                        <span class="cs-tag" style="background:${typeBg};color:${typeColor}">${carrier.type}</span>
                    </div>
                    <div class="cs-meta">
                        <span>历史 ${carrier.count || 0} 次</span>
                        <span>运输方式：${carrier.mode || '直拖'}</span>
                        <span>自有车队占比 ${carrier.self_owned_ratio || 0}%</span>
                    </div>
                    ${carrier.alternatives && carrier.alternatives.length > 0 ? `
                        <div class="cs-alts">
                            <span class="cs-alts-label">备选车队：</span>
                            ${carrier.alternatives.map(a => `<span class="cs-alt-tag">${a.carrier}（${a.type}，${a.count}次）</span>`).join('')}
                        </div>
                    ` : ''}
                </div>
            </div>
        `;
    }

    let shippingHtml = '';
    if (shippingLine.name) {
        const lines = (shippingLines.lines || []).slice(0, 5);
        shippingHtml = `
            <div class="cs-card">
                <div class="cs-card-header">
                    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" style="width:16px;height:16px"><path d="M3 18s1.5-2 4.5-2 4.5 2 9 2 4.5-2 4.5-2"/><path d="M21 12l-9-7-9 7"/><path d="M12 2l0 18"/></svg>
                    船公司
                </div>
                <div class="cs-card-body">
                    <div class="cs-primary">
                        <span class="cs-name">${shippingLine.name}</span>
                        <span class="cs-tag" style="background:rgba(184,134,11,0.1);color:var(--accent,#B8860B)">${shippingLine.code || ''}</span>
                    </div>
                    <div class="cs-meta">
                        <span>航程 ${shippingLine.transit_days || '?'} 天</span>
                        <span>${shippingLine.frequency || ''}</span>
                    </div>
                    <div class="cs-advantage">${shippingLine.advantage || ''}</div>
                    ${lines.length > 1 ? `
                        <div class="cs-alts">
                            <span class="cs-alts-label">其他可选船公司：</span>
                            ${lines.slice(1).map(l => `<span class="cs-alt-tag">${l.name}（${l.transit_days}天）</span>`).join('')}
                        </div>
                    ` : ''}
                </div>
            </div>
        `;
    }

    if (!carrierHtml && !shippingHtml) return '';

    return `
        <div class="carrier-shipping-section">
            <div class="cs-grid">
                ${carrierHtml}
                ${shippingHtml}
            </div>
        </div>
    `;
}

// ===== 时间线 =====
function renderTimeline(p) {
    const timeline = p.timeline || {};
    const cargoReady = timeline.cargo_ready || p.cargoReady || '—';
    const etd = timeline.etd || p.etd || '—';
    const eta = timeline.eta || p.eta || '—';

    const steps = [
        {
            title: '货好时间',
            date: cargoReady,
            desc: '货物在工厂完成生产',
            done: true,
            icon: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M22 11.08V12a10 10 0 1 1-5.93-9.14"/></svg>',
        },
        {
            title: '工厂发货',
            date: `预计 ${timeline.inland_days || '?'} 天后`,
            desc: '内陆运输至港口',
            icon: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><rect x="1" y="3" width="15" height="13"/><polygon points="16 8 20 8 23 11 23 16 16 16 16 8"/><circle cx="5.5" cy="18.5" r="2.5"/><circle cx="18.5" cy="18.5" r="2.5"/></svg>',
        },
        {
            title: '预计离港 (ETD)',
            date: etd,
            desc: `${timeline.ship_schedule || p.shipSchedule || '—'} 船期`,
            icon: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M3 18s1.5-2 4.5-2 4.5 2 9 2 4.5-2 4.5-2"/><path d="M21 12l-9-7-9 7"/><path d="M12 2l0 18"/></svg>',
        },
        {
            title: '海运在途',
            date: `${timeline.ocean_days || '?'} 天`,
            desc: '国际海运运输',
            icon: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M2 12h20"/><path d="M12 2a15.3 15.3 0 0 1 4 10 15.3 15.3 0 0 1-4 10 15.3 15.3 0 0 1-4-10 15.3 15.3 0 0 1 4-10z"/></svg>',
        },
        {
            title: '预计到港 (ETA)',
            date: eta,
            desc: `总周期 ${timeline.total_days || p.totalDays || '?'} 天`,
            icon: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M21 10c0 7-9 13-9 13s-9-6-9-13a9 9 0 0 1 18 0z"/><circle cx="12" cy="10" r="3"/></svg>',
        },
    ];

    let itemsHtml = '';
    steps.forEach((step, idx) => {
        itemsHtml += `
            <div class="timeline-item">
                <div class="timeline-dot ${step.done ? 'done' : ''}">${step.icon}</div>
                <div class="timeline-content">
                    <div class="timeline-title">${step.title}</div>
                    <div class="timeline-date">${step.date}</div>
                    <div class="timeline-desc">${step.desc}</div>
                </div>
            </div>
        `;
    });

    return `
        <div class="timeline-section">
            <div class="timeline-header">
                <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="10"/><polyline points="12 6 12 12 16 14"/></svg>
                运输时间线
            </div>
            <div class="timeline">
                ${itemsHtml}
            </div>
        </div>
    `;
}

// ===== AI 推荐理由 =====
function renderAIReasoning(reasoning, riskWarning, suggestion, data) {
    if (!reasoning && !riskWarning && !suggestion) return '';

    const tag = data.source === 'llm' ? 'AI 生成' : '规则引擎';

    let html = `
        <div class="reasoning-section">
            <div class="reasoning-header">
                <div class="ai-badge">
                    <svg viewBox="0 0 24 24" fill="none" stroke="#fff" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><polygon points="12 2 15.09 8.26 22 9.27 17 14.14 18.18 21.02 12 17.77 5.82 21.02 7 14.14 2 9.27 8.91 8.26 12 2"/></svg>
                </div>
                <h3>智能分析与推荐理由</h3>
                <span class="tag">${tag}</span>
            </div>
            <div class="reasoning-body">
    `;

    if (reasoning) {
        html += `<p><strong>推荐理由：</strong>${reasoning}</p>`;
    }
    if (riskWarning) {
        html += `<p style="color:var(--warning)"><strong>⚠ 风险提示：</strong>${riskWarning}</p>`;
    }
    if (suggestion) {
        html += `<p style="color:var(--accent2-dark)"><strong>💡 优化建议：</strong>${suggestion}</p>`;
    }

    html += `</div></div>`;
    return html;
}

// ===== 备选方案 =====
function renderAlternatives(alts) {
    if (!alts || alts.length === 0) return '';

    let cardsHtml = '';
    alts.forEach((alt, idx) => {
        const cost = alt.totalCostCny || alt.cost?.totalCny || 0;
        const days = alt.totalDays || 0;

        cardsHtml += `
            <div class="alt-card">
                <div class="alt-rank">${idx + 2}</div>
                <div class="alt-info">
                    <div class="alt-route">
                        <span>${alt.factoryShort || alt.factory}</span>
                        <span class="sep">→</span>
                        <span>${alt.departurePort || alt.origin_port || '—'}</span>
                        <span class="sep">→</span>
                        <span>${alt.destPort || alt.dest_port || '—'}</span>
                    </div>
                    <div class="alt-meta">
                        <span>📋 ${alt.tradeTerm || 'FOB'}</span>
                        <span>🚢 ${alt.oceanDays || alt.ocean_days || '?'}天海运</span>
                        <span>⏱ ${days}天</span>
                        ${alt.carrier?.recommended ? `<span>🚛 ${alt.carrier.recommended}</span>` : ''}
                        ${alt.shippingLine?.name ? `<span>⚓ ${alt.shippingLine.name}</span>` : ''}
                    </div>
                </div>
                <div class="alt-cost">
                    <b>¥${cost.toLocaleString()}</b>
                    <span>综合评分 ${alt.score || 0}</span>
                </div>
            </div>
        `;
    });

    return `
        <div class="alt-section">
            <div class="alt-header">
                <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><line x1="8" y1="6" x2="21" y2="6"/><line x1="8" y1="12" x2="21" y2="12"/><line x1="8" y1="18" x2="21" y2="18"/><line x1="3" y1="6" x2="3.01" y2="6"/><line x1="3" y1="12" x2="3.01" y2="12"/><line x1="3" y1="18" x2="3.01" y2="18"/></svg>
                备选方案
                <span class="count">${alts.length} 个方案</span>
            </div>
            <div class="alt-list">
                ${cardsHtml}
            </div>
        </div>
    `;
}

// ===== 海运费实时获取（支持多箱型）=====
async function fetchOceanFreightRate() {
    const loadingEl = document.getElementById('oceanLoading');
    const realtimeEl = document.getElementById('oceanRealtime');
    const errorEl = document.getElementById('oceanError');
    const errorDesc = document.getElementById('oceanErrorDesc');
    const refreshBtn = document.getElementById('oceanRefreshBtn');

    // 显示加载状态
    loadingEl.style.display = 'flex';
    realtimeEl.style.display = 'none';
    errorEl.style.display = 'none';
    refreshBtn.classList.add('loading');

    // 收集表单数据
    const productTypes = getMultiSelectValues('productTypeMulti');
    const productType = productTypes[0] || '';
    const destCountry = document.getElementById('destCountry')?.value || '';
    const boxTypes = getMultiSelectValues('boxTypeMulti');
    if (boxTypes.length === 0) boxTypes.push('40HQ');
    const cargoReady = document.getElementById('cargoReady')?.value || '';
    const shipSchedule = document.getElementById('shipSchedule')?.value || '';

    let routeInfo = null;
    let origin, destination;

    // Step 1: 通过后端知识库获取工厂→始发港 和 运抵国→目的港
    try {
        const routeUrl = new URL('/api/route-info', API_BASE);
        routeUrl.searchParams.set('productType', productType);
        routeUrl.searchParams.set('destCountry', destCountry);
        if (cargoReady) routeUrl.searchParams.set('cargoReady', cargoReady);
        if (shipSchedule) routeUrl.searchParams.set('shipSchedule', shipSchedule);
        routeUrl.searchParams.set('boxType', boxTypes[0]);

        const routeResp = await fetch(routeUrl.toString());
        const routeResult = await routeResp.json();

        if (routeResult.success && routeResult.data) {
            routeInfo = routeResult.data;
            origin = routeInfo.originPort;
            destination = routeInfo.destPort;
            console.log('[海运费] 路线查询成功:',
                routeInfo.factoryShort, '→', origin, '→', destination,
                '| 推荐航司:', routeInfo.recommendedShippingLine?.name || '无');

            // 自动推荐陆运费（根据工厂省份+路线报价卡）
            initLandFees(routeInfo.factoryProvince, 'direct',
                         routeInfo.factory || '', routeInfo.originPort || '');

            // 更新推荐航线信息卡片
            updateRouteInfoCard(routeInfo.factoryShort || routeInfo.factory || '',
                                routeInfo.originPort || '',
                                routeInfo.destPort || '');
        } else {
            console.warn('[海运费] 路线查询失败，回退到默认映射:', routeResult.error);
            const fallback = getOceanPortsByCountry(destCountry);
            origin = fallback.origin;
            destination = fallback.destination;
            const factoryInfo = getFallbackFactory(origin, productType);
            updateRouteInfoCard(factoryInfo.factoryShort, origin, destination);
        }
    } catch (e) {
        console.warn('[海运费] 路线查询异常，回退到默认映射:', e.message);
        const fallback = getOceanPortsByCountry(destCountry);
        origin = fallback.origin;
        destination = fallback.destination;
        const factoryInfo = getFallbackFactory(origin, productType);
        updateRouteInfoCard(factoryInfo.factoryShort, origin, destination);
    }

    // Step 2: 调用船公司比价接口
    try {
        const boxTypesQty = {};
        boxTypes.forEach(bt => { boxTypesQty[bt] = boxTypeCounts[bt] || 1; });

        const resp = await fetch(`${API_BASE}/api/freight-rate-compare`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ origin: origin, destination: destination, boxTypes: boxTypesQty }),
        });

        const result = await resp.json();

        if (result.success && result.data) {
            const d = result.data;
            const cheapest = d.cheapest;
            // 过滤：只保留对所有选定箱型都有报价的船公司
            const allCarriers = (d.carriers || []).filter(function(c) { return c.hasAllTypes; });
            const carriers = allCarriers;
            // 重新确定最便宜的（过滤后第一个就是，因为后端已排序）
            const realCheapest = carriers.length > 0 ? carriers[0] : null;

            // 更新价格摘要：中间卡片显示USD总价，顶部海运费合计和输入框是CNY
            document.getElementById('oceanMedianRate').textContent =
                realCheapest ? '$' + Number(realCheapest.totalUsd).toLocaleString() : '—';

            // 航线信息
            var boxTypeSummaryParts = [];
            boxTypes.forEach(function(bt) {
                boxTypeSummaryParts.push(bt + '×' + (boxTypeCounts[bt] || 1));
            });
            var boxTypeSummary = boxTypeSummaryParts.join(' + ');
            document.getElementById('oceanRouteInfo').textContent =
                origin + ' → ' + destination + ' · ' + boxTypeSummary;

            // 转运天数 / 船公司数量
            var transitParts = [];
            if (routeInfo && routeInfo.transitDays) {
                transitParts.push(routeInfo.transitDays + '天转运');
            }
            transitParts.push(carriers.length + '家船公司');
            document.getElementById('oceanTransitInfo').textContent = transitParts.join(' · ');

            // 获取时间
            var fetchTime = d.fetchedAt
                ? new Date(d.fetchedAt).toLocaleString('zh-CN', { month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit' })
                : '刚刚';
            document.getElementById('oceanFetchedAt').textContent = '📄 合约表 · ' + fetchTime;

            // 渲染各船公司报价卡片（可点击选择）— 全USD展示
            var quotesListEl = document.getElementById('oceanQuotesList');
            var quotesGridEl = document.getElementById('oceanQuotesGrid');

            var cardsHtml = carriers.map(function(c, idx) {
                var isCheapest = idx === 0;
                var cardClass = 'ocean-quote-card' + (c.isValid ? ' valid' : '') + (isCheapest ? ' cheapest' : '');
                var prefix = isCheapest ? '⭐ ' : '';
                var validBadge = c.isValid
                    ? '<span class="ocean-quote-valid yes">有效</span>'
                    : '<span class="ocean-quote-valid no">过期</span>';
                var perTypeHtml = '';
                if (c.perTypeDetail) {
                    perTypeHtml = Object.keys(c.perTypeDetail).map(function(bt) {
                        var pd = c.perTypeDetail[bt];
                        var rateDisplay = (pd.currency === 'USD' ? '$' : '¥') + Number(pd.rate).toLocaleString();
                        // 小计也用USD显示（与用户要求一致）
                        var subtotalUsd = pd.rate !== null && pd.rate !== undefined
                            ? Number(pd.rate * pd.qty).toLocaleString()
                            : '—';
                        return '<div class="ocean-quote-pertype">' +
                            bt + ': ' + rateDisplay + ' × ' + pd.qty +
                            ' = $' + subtotalUsd +
                            '</div>';
                    }).join('');
                }
                var hasAllBadge = c.hasAllTypes ? ' · ✔全箱型' : '';
                return '<div class="' + cardClass + '" data-carrier-idx="' + idx + '" style="cursor:pointer" title="点击选择此船公司">' +
                    '<div class="ocean-quote-head">' +
                    '<span class="ocean-quote-carrier">' + prefix + c.carrier + '</span>' +
                    '<span class="ocean-quote-rate">$' + Number(c.totalUsd).toLocaleString() + '</span>' +
                    '</div>' +
                    '<div class="ocean-quote-meta">' +
                    validBadge + hasAllBadge +
                    '</div>' +
                    perTypeHtml +
                    '</div>';
            }).join('');
            quotesGridEl.innerHTML = cardsHtml;
            quotesListEl.style.display = 'block';

            // 默认选中第一个（最便宜）
            var firstCard = quotesGridEl.querySelector('.ocean-quote-card');
            if (firstCard) firstCard.classList.add('selected');

            // 卡片点击事件（事件委托）
            quotesGridEl.querySelectorAll('.ocean-quote-card').forEach(function(card) {
                card.addEventListener('click', function() {
                    var idx = parseInt(this.getAttribute('data-carrier-idx'));
                    var carrier = carriers[idx];
                    if (!carrier) return;
                    // 更新选中状态
                    quotesGridEl.querySelectorAll('.ocean-quote-card').forEach(function(el) { el.classList.remove('selected'); });
                    this.classList.add('selected');
                    // 更新费用
                    var oceanFeeInput = document.getElementById('oceanFee');
                    oceanFeeInput.value = carrier.totalCny;
                    feeData.ocean.fee = carrier.totalCny;
                    feeData.ocean.selectedCarrier = carrier;
                    feeData.ocean.allCarriers = carriers;
                    updateGrandTotal();
                    document.getElementById('oceanMedianRate').textContent = '¥' + carrier.totalCny.toLocaleString();
                    document.getElementById('oceanMaxRate').textContent = '$' + carrier.totalUsd.toLocaleString();
                    console.log('[海运费] 用户选择船公司:', carrier.carrier, '¥' + carrier.totalCny);
                });
            });

            // 更新推荐航司信息
            if (routeInfo && routeInfo.recommendedShippingLine) {
                var rec = routeInfo.recommendedShippingLine;
                var lineEl = document.getElementById('oceanShippingLine');
                if (lineEl) {
                    lineEl.textContent = '推荐航司: ' + rec.name + ' (' + rec.code + ') · ' + rec.transit_days + '天 · ' + rec.frequency;
                }
            }

            // 更新工厂和FCL/普货标签
            if (routeInfo) {
                var factoryEl = document.getElementById('oceanFactoryTag');
                if (factoryEl) {
                    factoryEl.textContent = routeInfo.factoryShort + ' · ' + origin;
                }
            }

            // 显示合约区域
            loadingEl.style.display = 'none';
            errorEl.style.display = 'none';
            realtimeEl.style.display = 'block';

            // 自动将最便宜船公司总价填入输入框
            if (realCheapest) {
                var oceanFeeInput = document.getElementById('oceanFee');
                var currentVal = parseFloat(oceanFeeInput.value) || 0;
                if (!oceanFeeInput.value || currentVal === 2500 || currentVal === 900 || currentVal === 0) {
                    oceanFeeInput.value = realCheapest.totalCny;
                    feeData.ocean.fee = realCheapest.totalCny;
                    feeData.ocean.cheapestCarrier = realCheapest;
                    feeData.ocean.allCarriers = carriers;
                    updateGrandTotal();
                }
            }

            console.log('[海运费] 船公司比价成功:', origin, '→', destination,
                allCarriers.length + '家(全箱型' + carriers.length + '家), 最低: ' + (realCheapest ? realCheapest.carrier + ' ¥' + realCheapest.totalCny : '无'));
        } else {
            throw new Error(result.error || '未获取到海运费报价数据');
        }
    } catch (e) {
        console.error('[海运费] 合约报价获取失败:', e);
        loadingEl.style.display = 'none';
        realtimeEl.style.display = 'none';
        errorEl.style.display = 'flex';

        const msg = e.message || '';
        if (msg.includes('未找到匹配') || msg.includes('未匹配') || msg.includes('404')) {
            errorDesc.textContent = '该航线未在合约文件中找到匹配报价，请调整港口/箱型，或手动输入海运费金额';
        } else if (msg.includes('文件未找到') || msg.includes('加载失败')) {
            errorDesc.textContent = '合约运费文件加载失败，请确认文件存在或手动输入海运费';
        } else if (msg.includes('Failed to fetch') || msg.includes('NetworkError')) {
            errorDesc.textContent = '后端服务未启动或无法连接，请启动后端（py main.py）后重试';
        } else {
            errorDesc.textContent = msg || '获取合约报价失败，请手动输入海运费金额';
        }
    } finally {
        refreshBtn.classList.remove('loading');
    }
}

// 根据目的国和始发港推断最可能的发货工厂（回退方案）
function getFallbackFactory(originPort, productType) {
    // 根据始发港推断工厂
    var portFactoryMap = {
        '青岛/QINGDAO': '山东英科医疗制品有限公司',
        '上海/SHANGHAI': '安徽英科医疗用品有限公司',
        '深圳/SHENZHEN': '江西英科医疗有限公司',
        '海防/HAIPHONG': 'BASIC INTERNATIONAL VIET NAM CO..LTD',
        '勿拉湾/BELAWAN': 'PT BASIC INTERNATIONAL SUMATERA',
    };
    var factory = portFactoryMap[originPort] || '安徽英科医疗用品有限公司';
    var shortNameMap = {
        '山东英科医疗制品有限公司': '山东英科',
        '安徽英科医疗用品有限公司': '安徽英科',
        '江西英科医疗有限公司': '江西英科',
        'BASIC INTERNATIONAL VIET NAM CO..LTD': '越南英科',
        'PT BASIC INTERNATIONAL SUMATERA': '印尼英科',
    };
    return { factory: factory, factoryShort: shortNameMap[factory] || factory };
}

// 根据目的国获取标准航线港口（回退方案，仅在后端 /api/route-info 不可用时使用）
function getOceanPortsByCountry(country) {
    var routeMap = {
        '美国': { origin: '青岛/QINGDAO', destination: '洛杉矶/LOS ANGELES' },
        '加拿大': { origin: '青岛/QINGDAO', destination: '洛杉矶/LOS ANGELES' },
        '墨西哥': { origin: '青岛/QINGDAO', destination: '洛杉矶/LOS ANGELES' },
        '英国': { origin: '上海/SHANGHAI', destination: '鹿特丹/ROTTERDAM' },
        '德国': { origin: '上海/SHANGHAI', destination: '汉堡/HAMBURG' },
        '法国': { origin: '上海/SHANGHAI', destination: '鹿特丹/ROTTERDAM' },
        '荷兰': { origin: '上海/SHANGHAI', destination: '鹿特丹/ROTTERDAM' },
        '比利时': { origin: '上海/SHANGHAI', destination: '安特卫普/ANTWERP' },
        '意大利': { origin: '上海/SHANGHAI', destination: '鹿特丹/ROTTERDAM' },
        '西班牙': { origin: '上海/SHANGHAI', destination: '鹿特丹/ROTTERDAM' },
        '澳大利亚': { origin: '上海/SHANGHAI', destination: '悉尼/SYDNEY' },
        '新西兰': { origin: '上海/SHANGHAI', destination: '墨尔本/MELBOURNE' },
        '日本': { origin: '上海/SHANGHAI', destination: '东京/TOKYO' },
        '韩国': { origin: '青岛/QINGDAO', destination: '釜山/BUSAN' },
        '新加坡': { origin: '深圳/SHENZHEN', destination: '新加坡' },
        '马来西亚': { origin: '深圳/SHENZHEN', destination: '巴生港/PORT KLANG' },
        '泰国': { origin: '深圳/SHENZHEN', destination: '新加坡' },
        '印度尼西亚': { origin: '深圳/SHENZHEN', destination: '勿拉湾/BELAWAN' },
        '越南': { origin: '深圳/SHENZHEN', destination: '海防/HAIPHONG' },
        '印度': { origin: '上海/SHANGHAI', destination: '迪拜/DUBAI' },
        '阿联酋': { origin: '上海/SHANGHAI', destination: '迪拜/DUBAI' },
        '沙特阿拉伯': { origin: '上海/SHANGHAI', destination: '迪拜/DUBAI' },
        '巴西': { origin: '上海/SHANGHAI', destination: '洛杉矶/LOS ANGELES' },
    };

    if (country && routeMap[country]) {
        return routeMap[country];
    }
    return { origin: '上海/SHANGHAI', destination: '洛杉矶/LOS ANGELES' };
}

// 港杂费推荐（根据始发港/贸易条款/箱型查询标准表）
async function fetchPortMiscFee(originPort, tradeTerm, boxTypes) {
    if (!originPort || originPort === '—') return;
    var bt = (boxTypes && boxTypes.length > 0) ? boxTypes[0] : '40HQ';
    var tt = tradeTerm || 'FOB';

    try {
        var url = API_BASE + '/api/port-misc-fee?originPort=' + encodeURIComponent(originPort) +
            '&tradeTerm=' + encodeURIComponent(tt) + '&boxType=' + encodeURIComponent(bt);
        var resp = await fetch(url);
        var result = await resp.json();
        if (result.success && result.data) {
            var perBoxFee = result.data.recommendedFee;
            var totalBoxes = parseInt(document.getElementById('boxes')?.value) || 1;
            var fee = Math.round(perBoxFee * totalBoxes * 100) / 100;
            var input = document.getElementById('portMiscFee');
            if (input) {
                input.value = fee;
                feeData.portMisc.fee = fee;
                var summary = document.getElementById('portMiscFeeSummary');
                if (summary) summary.textContent = '¥' + formatFee(fee);
                updateGrandTotal();
            }
            console.log('[港杂费] 推荐:', originPort, tt, bt,
                '单箱¥' + perBoxFee + ' × ' + totalBoxes + '箱 = ¥' + fee,
                '(' + result.data.totalMatched + '条标准记录)');
        }
    } catch (e) {
        console.warn('[港杂费] 查询失败:', e.message);
    }
}

// 陆运费推荐（从各路线报价卡实时查询）
async function fetchLandFreightFromRoute(factoryName, originPort, transportMode) {
    if (!factoryName || !originPort) return;
    var boxTypes = getMultiSelectValues('boxTypeMulti');
    var bt = (boxTypes && boxTypes.length > 0) ? boxTypes[0] : '40HQ';

    try {
        var url = API_BASE + '/api/land-freight?factory=' + encodeURIComponent(factoryName) +
            '&originPort=' + encodeURIComponent(originPort) +
            '&transportMode=' + encodeURIComponent(transportMode || 'direct') +
            '&boxType=' + encodeURIComponent(bt);
        var resp = await fetch(url);
        var result = await resp.json();
        if (result.success && result.data) {
            var d = result.data;
            var landFee = d.recommendedLandFreight;
            var tollFeeRec = d.recommendedTollFreight || 0;

            // 更新陆运费输入框
            var baseFreightInput = document.getElementById('landBaseFreight');
            if (baseFreightInput && landFee > 0) {
                baseFreightInput.value = landFee;
                feeData.land.baseFreight = landFee;
            }

            // 更新高速费（如果报价卡有高速费数据）
            if (tollFeeRec > 0) {
                var tollFeeInput = document.getElementById('landTollFee');
                if (tollFeeInput) {
                    tollFeeInput.value = tollFeeRec;
                    feeData.land.tollFee = tollFeeRec;
                }
            }

            updateGrandTotal();

            console.log('[陆运费] 路线报价卡推荐:', factoryName, originPort, transportMode,
                '陆运费¥' + landFee, '高速费¥' + tollFeeRec,
                '(Sheet: ' + d.sheetName + ', ' + d.totalMatched + '条记录)');
        } else {
            console.warn('[陆运费] 路线报价卡未匹配:', result.error || '无数据，使用默认值');
        }
    } catch (e) {
        console.warn('[陆运费] 查询失败:', e.message);
    }
}

// 更新弹窗中的推荐航线信息卡片
function updateRouteInfoCard(factory, originPort, destPort) {
    const factoryEl = document.getElementById('routeInfoFactory');
    const originEl = document.getElementById('routeInfoOrigin');
    const destEl = document.getElementById('routeInfoDest');
    if (factoryEl) factoryEl.textContent = factory || '—';
    if (originEl) originEl.textContent = originPort || '—';
    if (destEl) destEl.textContent = destPort || '—';
}

// ===== 费用编辑面板（移动原弹窗内容到结果中，避免ID重复） =====
function renderFeePanel(data) {
    var container = document.querySelector('.results-container');
    if (!container) return;

    // 如果已有面板，先把费用内容移回弹窗body
    var existPanel = document.getElementById('feePanelInResults');
    var modalBody = document.getElementById('costInfoBody');
    if (existPanel && modalBody) {
        var sections = existPanel.querySelectorAll('.fee-section, .route-info-card, .ocean-realtime, .ocean-loading, .ocean-error, .fee-item, .fee-total-row');
        for (var i = 0; i < sections.length; i++) {
            modalBody.appendChild(sections[i]);
        }
        existPanel.remove();
    }

    var modalBody = document.getElementById('costInfoBody');
    if (!modalBody) return;

    // 创建包装容器
    var wrapper = document.createElement('div');
    wrapper.id = 'feePanelInResults';

    // 标题
    var title = document.createElement('h3');
    title.style.cssText = 'font-size:0.9rem;font-weight:700;color:var(--ink);margin-bottom:0.6rem;display:flex;align-items:center;gap:0.4rem';
    title.innerHTML = '<span>💰</span> 费用信息确认（修改后点重新优化）';
    wrapper.appendChild(title);

    // 移动弹窗body的所有子元素到wrapper
    while (modalBody.firstChild) {
        wrapper.appendChild(modalBody.firstChild);
    }

    // 重新优化按钮
    var btn = document.createElement('button');
    btn.type = 'button';
    btn.className = 'reoptimize-btn';
    btn.innerHTML = '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" style="width:16px;height:16px;vertical-align:middle;margin-right:4px"><polyline points="23 4 23 10 17 10"/><path d="M20.49 15a9 9 0 1 1-2.12-9.36L23 10"/></svg> 重新优化';
    btn.addEventListener('click', reOptimize);
    wrapper.appendChild(btn);

    // 插入到路线可视化下方的占位符位置
    var placeholder = document.getElementById('feePanelPlaceholder');
    if (placeholder) {
        placeholder.parentNode.insertBefore(wrapper, placeholder);
    } else {
        container.appendChild(wrapper);
    }

    // 隐藏费用面板中的路线信息卡片（已在结果最上方显示）
    var ric = wrapper.querySelector('#routeInfoCard');
    if (ric) ric.style.display = 'none';

    // 绑定费用section折叠/展开（默认陆运费展开，其余收起）
    wrapper.querySelectorAll('.fee-section').forEach(function(s) {
        var group = s.getAttribute('data-fee-group');
        if (group === 'land') s.classList.add('open');  // 只有陆运费默认展开
    });
    wrapper.querySelectorAll('.fee-section-header').forEach(function(header) {
        // 移除旧监听器避免重复绑定（通过克隆节点）
        var newHeader = header.cloneNode(true);
        header.parentNode.replaceChild(newHeader, header);
        newHeader.addEventListener('click', function() {
            var section = newHeader.closest('.fee-section');
            if (section) section.classList.toggle('open');
        });
    });

    // 同步当前feeData到移动后的输入框
    var lbf = document.getElementById('landBaseFreight');
    if (lbf) lbf.value = feeData.land.baseFreight;
    var of = document.getElementById('oceanFee');
    if (of) of.value = feeData.ocean.fee;
    var pmf = document.getElementById('portMiscFee');
    if (pmf) pmf.value = feeData.portMisc.fee;
    var vf = document.getElementById('vgmFee');
    if (vf) vf.value = feeData.seaManager.vgmFee;
    var ltf = document.getElementById('landTollFee');
    if (ltf) ltf.value = feeData.land.tollFee;
    var ilf = document.getElementById('insideLoadFee');
    if (ilf) ilf.value = feeData.land.insideLoadFee;

    // 触发合约报价加载
    autoEnableICS2ForEurope();
    setTimeout(function() {
        fetchOceanFreightRate();
        // 港杂费推荐：从路线信息条获取始发港和贸易条款
        var originPort = document.getElementById('routeInfoOrigin')?.textContent || '';
        var tradeTerm = (data.primary && data.primary.tradeTerm) ? data.primary.tradeTerm : 'FOB';
        var boxTypes = getMultiSelectValues('boxTypeMulti');
        fetchPortMiscFee(originPort, tradeTerm, boxTypes);
    }, 400);
}

// ===== 旧版费用编辑面板（保留备用） =====
function renderFeeEditPanel(data) {
    var primary = data.primary;
    var items = (primary.cost && primary.cost.items) ? primary.cost.items : [];
    var totalCny = (primary.cost && primary.cost.totalCny) ? primary.cost.totalCny : 0;
    var totalUsd = (primary.cost && primary.cost.totalUsd) ? primary.cost.totalUsd : 0;

    var container = document.querySelector('.results-container');
    if (!container) return;

    // 移除已有的费用编辑面板
    var existing = document.getElementById('feeEditPanel');
    if (existing) existing.remove();

    var html = '';
    html += '<div id="feeEditPanel" class="fee-edit-panel">';

    // 标题栏（可折叠）
    html += '<div class="fee-edit-header" onclick="var p=this.closest(\'.fee-edit-panel\');p.classList.toggle(\'collapsed\')">';
    html += '<h3><span style="margin-right:6px">💰</span> 费用调整（点击修改后重新优化）</h3>';
    html += '<span class="fee-edit-toggle">▼</span>';
    html += '</div>';

    html += '<div class="fee-edit-body">';

    // 可编辑的费用字段
    for (var i = 0; i < items.length; i++) {
        var item = items[i];
        var amount = item.amount_cny || item.amount || 0;
        var usd = item.amount_usd || 0;
        html += '<div class="fee-edit-row">';
        html += '<span class="fee-edit-label">' + (i + 1) + '. ' + (item.name || '费用项') + '</span>';
        if (item.basis) {
            html += '<span class="fee-edit-basis">' + item.basis + '</span>';
        }
        html += '<input type="number" class="fee-edit-input" data-fee-index="' + i + '" value="' + amount + '" step="0.01" min="0">';
        html += '<span class="fee-edit-unit">¥</span>';
        if (usd) {
            html += '<span class="fee-edit-usd">≈ $' + Number(usd).toLocaleString() + '</span>';
        }
        html += '</div>';
    }

    // 其他费用分区
    html += '<div class="fee-edit-divider"></div>';
    html += '<div class="fee-edit-subtitle">其他费用</div>';
    html += '<div id="otherFeesContainer">';
    for (var j = 0; j < feeData.other.length; j++) {
        var o = feeData.other[j];
        html += '<div class="fee-edit-row other-fee-edit-row">';
        html += '<input type="text" class="other-fee-edit-name" value="' + (o.name || '') + '" placeholder="费用名称">';
        html += '<input type="number" class="other-fee-edit-amount" value="' + (o.amount || 0) + '" placeholder="金额" step="0.01" min="0">';
        html += '<span class="fee-edit-unit">¥</span>';
        html += '<button type="button" class="other-fee-edit-remove" onclick="this.parentElement.remove();updateFeeEditTotal()">×</button>';
        html += '</div>';
    }
    html += '</div>';
    html += '<button type="button" class="add-other-fee-btn" onclick="addOtherFeeEditRow()">+ 添加其他费用</button>';

    // 合计和重新优化按钮
    html += '<div class="fee-edit-total-row">';
    html += '<span class="fee-edit-total-label">费用合计：</span>';
    html += '<span id="feeEditTotal">¥' + totalCny.toLocaleString() + '</span>';
    if (totalUsd) {
        html += '<span class="fee-edit-total-usd">≈ $' + totalUsd.toLocaleString() + '</span>';
    }
    html += '</div>';
    html += '<button type="button" class="reoptimize-btn" onclick="reOptimize()">';
    html += '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" style="width:16px;height:16px;vertical-align:middle;margin-right:4px">';
    html += '<polyline points="23 4 23 10 17 10"/>';
    html += '<path d="M20.49 15a9 9 0 1 1-2.12-9.36L23 10"/>';
    html += '</svg>';
    html += '重新优化';
    html += '</button>';

    html += '</div>'; // fee-edit-body
    html += '</div>'; // fee-edit-panel

    container.insertAdjacentHTML('beforeend', html);

    // 绑定输入事件，实时更新合计
    var inputs = document.querySelectorAll('#feeEditPanel .fee-edit-input');
    for (var k = 0; k < inputs.length; k++) {
        inputs[k].addEventListener('input', updateFeeEditTotal);
    }
    var otherAmts = document.querySelectorAll('#feeEditPanel .other-fee-edit-amount');
    for (var m = 0; m < otherAmts.length; m++) {
        otherAmts[m].addEventListener('input', updateFeeEditTotal);
    }
}

// ===== 费用编辑面板 - 更新合计 =====
function updateFeeEditTotal() {
    var inputs = document.querySelectorAll('#feeEditPanel .fee-edit-input');
    var total = 0;
    for (var i = 0; i < inputs.length; i++) {
        total += parseFloat(inputs[i].value) || 0;
    }
    var otherAmounts = document.querySelectorAll('#feeEditPanel .other-fee-edit-amount');
    for (var j = 0; j < otherAmounts.length; j++) {
        total += parseFloat(otherAmounts[j].value) || 0;
    }
    var totalEl = document.getElementById('feeEditTotal');
    if (totalEl) {
        totalEl.textContent = '¥' + total.toLocaleString();
    }
    // 同步到全局 feeData 并更新页面顶部合计
    syncFeeEditToFeeData();
    updateGrandTotal();
}

// ===== 费用编辑面板 - 同步到全局 feeData =====
function syncFeeEditToFeeData() {
    var inputs = document.querySelectorAll('#feeEditPanel .fee-edit-input');
    for (var i = 0; i < inputs.length; i++) {
        var input = inputs[i];
        var row = input.closest('.fee-edit-row');
        var labelEl = row ? row.querySelector('.fee-edit-label') : null;
        if (!labelEl) continue;
        var name = labelEl.textContent.replace(/^\d+\.\s*/, '');
        var amount = parseFloat(input.value) || 0;
        // 按费用名称映射到 feeData
        if (name.indexOf('内装') >= 0) {
            feeData.land.insideLoadFee = amount;
            feeData.land.insideLoadEnabled = amount > 0;
        } else if (name.indexOf('高速') >= 0) {
            feeData.land.tollFee = amount;
            feeData.land.tollEnabled = amount > 0;
        } else if (name.indexOf('陆运') >= 0) {
            feeData.land.baseFreight = amount;
        } else if (name.indexOf('海运') >= 0 || name.indexOf('OCEAN') >= 0) {
            feeData.ocean.fee = amount;
        } else if (name.indexOf('港杂') >= 0 || name.indexOf('码头') >= 0) {
            feeData.portMisc.fee = amount;
        } else if (name.indexOf('舱单') >= 0) {
            feeData.seaManager.manifestFee = amount;
        } else if (name.indexOf('VGM') >= 0) {
            feeData.seaManager.vgmFee = amount;
        } else if (name.indexOf('ICS') >= 0) {
            feeData.seaManager.ics2Fee = amount;
            feeData.seaManager.ics2Enabled = amount > 0;
        }
    }
    // 同步其他费用
    var otherNames = document.querySelectorAll('#feeEditPanel .other-fee-edit-name');
    var otherAmounts = document.querySelectorAll('#feeEditPanel .other-fee-edit-amount');
    feeData.other = [];
    for (var j = 0; j < otherNames.length; j++) {
        feeData.other.push({
            name: otherNames[j].value || '其他费用',
            amount: parseFloat(otherAmounts[j].value) || 0
        });
    }
}

// ===== 添加其他费用行 =====
function addOtherFeeEditRow() {
    var container = document.getElementById('otherFeesContainer');
    if (!container) return;
    var row = document.createElement('div');
    row.className = 'fee-edit-row other-fee-edit-row';
    row.innerHTML = '<input type="text" class="other-fee-edit-name" placeholder="费用名称">' +
        '<input type="number" class="other-fee-edit-amount" placeholder="金额" step="0.01" min="0">' +
        '<span class="fee-edit-unit">¥</span>' +
        '<button type="button" class="other-fee-edit-remove" onclick="this.parentElement.remove();updateFeeEditTotal()">×</button>';
    container.appendChild(row);
    row.querySelector('.other-fee-edit-amount').addEventListener('input', updateFeeEditTotal);
}

// ===== 重新优化（使用修改后的费用数据重新提交） =====
async function reOptimize() {
    if (!lastSubmitPayload) {
        alert('请先提交一次查询');
        return;
    }

    // 收集修改后的费用
    var feeInputs = document.querySelectorAll('#feeEditPanel .fee-edit-input');
    var modifiedCostItems = [];
    var totalCny = 0;
    for (var i = 0; i < feeInputs.length; i++) {
        var input = feeInputs[i];
        var row = input.closest('.fee-edit-row');
        var labelEl = row ? row.querySelector('.fee-edit-label') : null;
        var name = labelEl ? labelEl.textContent.replace(/^\d+\.\s*/, '') : '费用项';
        var amount = parseFloat(input.value) || 0;
        modifiedCostItems.push({ name: name, amount_cny: amount });
        totalCny += amount;
    }

    // 收集其他费用
    var otherNames = document.querySelectorAll('#feeEditPanel .other-fee-edit-name');
    var otherAmounts = document.querySelectorAll('#feeEditPanel .other-fee-edit-amount');
    var otherFees = [];
    for (var j = 0; j < otherNames.length; j++) {
        var oName = otherNames[j].value || '其他费用';
        var oAmt = parseFloat(otherAmounts[j].value) || 0;
        otherFees.push({ name: oName, amount: oAmt });
        totalCny += oAmt;
    }

    feeData.other = otherFees;

    // 更新提交数据
    var payload = JSON.parse(JSON.stringify(lastSubmitPayload));
    payload.costInfo = {
        total: totalCny,
        details: feeData,
        modifiedCostItems: modifiedCostItems
    };

    showLoading();
    submitBtn.disabled = true;

    try {
        var resp = await fetch(API_BASE + '/api/logistics/recommend', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(payload),
        });

        if (!resp.ok) throw new Error('HTTP ' + resp.status);

        var result = await resp.json();
        if (result.success) {
            lastSubmitPayload = payload;
            renderResult(result.data);
            renderFeePanel(result.data);
            renderAlternativesAfterResults(result.data.alternatives || []);
            // 滚动到结果区域
            var resultsContainer = document.querySelector('.results-container');
            if (resultsContainer) {
                resultsContainer.scrollIntoView({ behavior: 'smooth', block: 'start' });
            }
        } else {
            throw new Error(result.error || '推荐生成失败');
        }
    } catch (e) {
        console.error('[API] 错误:', e);
        showError('重新优化失败，请确认后端服务已启动（http://localhost:5000）');
    } finally {
        submitBtn.disabled = false;
    }
}

// ===== 在费用编辑面板之后渲染备选方案 =====
function renderAlternativesAfterResults(alts) {
    if (!alts || alts.length === 0) return;
    var container = document.querySelector('.results-container');
    if (!container) return;
    // 移除已有的备选方案
    var existing = container.querySelector('.alt-section');
    if (existing) existing.remove();
    container.insertAdjacentHTML('beforeend', renderAlternatives(alts));
}
