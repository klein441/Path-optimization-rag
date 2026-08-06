/**
 * 物流运输路径智能优化系统 — 前端交互逻辑
 */

// ===== API 配置 =====
const API_BASE = 'http://localhost:5000';

// ===== 全局费用数据 =====
let feeData = {
    land: { tollEnabled: false, tollFee: 0, insideLoadEnabled: false, insideLoadFee: 0 },
    seaManager: { manifestFee: 55, manifestCustom: 0, manifestMode: 'default', vgmFee: 5, ics2Enabled: false, ics2Fee: 0 },
    portMisc: { fee: 320 },
    ocean: { fee: 2500 },
    other: [] // [{name, amount}]
};

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
    setupCostInfoModal();
    setupFeeCalculations();
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

// ===== 费用信息确认模态框 =====
function setupCostInfoModal() {
    const openBtn = document.getElementById('costInfoBtn');
    const modal = document.getElementById('costInfoModal');
    const closeBtn = document.getElementById('costInfoClose');
    const confirmBtn = document.getElementById('costInfoConfirm');

    openBtn.addEventListener('click', () => {
        modal.classList.add('open');
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
    const applyBtn = document.getElementById('oceanApplyBtn');
    if (applyBtn) {
        applyBtn.addEventListener('click', () => {
            const medianRate = document.getElementById('oceanMedianRate').textContent;
            const num = parseFloat(medianRate);
            if (!isNaN(num) && num > 0) {
                // USD -> CNY 转换
                const cny = Math.round(num * 7.2 * 100) / 100;
                const oceanFeeInput = document.getElementById('oceanFee');
                oceanFeeInput.value = cny;
                feeData.ocean.fee = cny;
                updateGrandTotal();
                // 显示应用提示
                applyBtn.textContent = '✓ 已应用';
                setTimeout(() => { applyBtn.textContent = '应用中位价'; }, 1500);
            }
        });
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
                <span>已确认费用信息：陆运费 <b>¥${formatFee(feeData.land.tollFee + feeData.land.insideLoadFee)}</b> + 海管家 <b>¥${formatFee(getSeaManagerTotal())}</b> + 港杂 <b>¥${formatFee(feeData.portMisc.fee)}</b> + 海运 <b>¥${formatFee(feeData.ocean.fee)}</b> + 其他 <b>¥${formatFee(getOtherTotal())}</b></span>
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
            <div class="fee-detail-group-title">陆运费</div>
            <div class="fee-detail-row"><span class="label">拖车费（高速费）</span><span class="value">¥${formatFee(feeData.land.tollFee)}</span></div>
            <div class="fee-detail-row"><span class="label">内装费</span><span class="value">¥${formatFee(feeData.land.insideLoadFee)}</span></div>
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
    // 陆运费 - 高速费
    const tollToggle = document.getElementById('landTollToggle');
    const tollFee = document.getElementById('landTollFee');
    const tollUnit = tollFee?.nextElementSibling;

    tollToggle.addEventListener('change', () => {
        feeData.land.tollEnabled = tollToggle.checked;
        tollFee.style.display = tollToggle.checked ? '' : 'none';
        if (tollUnit) tollUnit.style.display = tollToggle.checked ? '' : 'none';
        if (!tollToggle.checked) {
            tollFee.value = 0;
            feeData.land.tollFee = 0;
        }
        updateGrandTotal();
    });

    tollFee.addEventListener('input', () => {
        feeData.land.tollFee = parseFloat(tollFee.value) || 0;
        updateGrandTotal();
    });

    // 陆运费 - 内装费
    const insideToggle = document.getElementById('insideLoadToggle');
    const insideFee = document.getElementById('insideLoadFee');
    const insideUnit = insideFee?.nextElementSibling;

    insideToggle.addEventListener('change', () => {
        feeData.land.insideLoadEnabled = insideToggle.checked;
        insideFee.style.display = insideToggle.checked ? '' : 'none';
        if (insideUnit) insideUnit.style.display = insideToggle.checked ? '' : 'none';
        if (!insideToggle.checked) {
            insideFee.value = 0;
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

function getSeaManagerTotal() {
    return feeData.seaManager.manifestFee + feeData.seaManager.vgmFee + feeData.seaManager.ics2Fee;
}

function getOtherTotal() {
    return feeData.other.reduce((sum, o) => sum + (parseFloat(o.amount) || 0), 0);
}

function calculateAllFees() {
    const landTotal = feeData.land.tollFee + feeData.land.insideLoadFee;
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
    document.getElementById('grandTotal').textContent = '¥' + formatFee(grandTotal);

    document.getElementById('landFeeSummary').textContent = '¥' + formatFee(feeData.land.tollFee + feeData.land.insideLoadFee);
    document.getElementById('seaManagerFeeSummary').textContent = '¥' + formatFee(getSeaManagerTotal());
    document.getElementById('portMiscFeeSummary').textContent = '¥' + formatFee(feeData.portMisc.fee);
    document.getElementById('oceanFeeSummary').textContent = '¥' + formatFee(feeData.ocean.fee);
    document.getElementById('otherFeeSummary').textContent = '¥' + formatFee(getOtherTotal());
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

    const payload = {
        customer: document.getElementById('customer').value,
        productType: productTypes.join(','),
        productTypes: productTypes,
        boxTypes: boxTypes,
        destCountry: document.getElementById('destCountry').value,
        boxCount: parseInt(document.getElementById('boxes').value) || 0,
        weight: parseFloat(document.getElementById('weight').value) || 0,
        volume: parseFloat(document.getElementById('volume').value) || 0,
        cargoReady: document.getElementById('cargoReady').value,
        shipSchedule: document.getElementById('shipSchedule').value,
        transportPref: document.getElementById('transportPref').value,
        tradePref: document.getElementById('tradePref').value,
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
            renderResult(result.data);
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
            ${renderRouteViz(primary)}
            ${renderSummaryBanner(primary, alternatives)}
            ${renderRecCards(primary)}
            ${renderCostBreakdown(primary)}
            ${renderCarrierAndShipping(primary)}
            ${renderTimeline(primary)}
            ${renderAIReasoning(reasoning, riskWarning, optimizationSuggestion, data)}
            ${renderAlternatives(alternatives)}
        </div>
    `;
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
                    费用明细（共 ${items.length} 项 · ${boxCount} 个集装箱）
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
        const typeColor = carrier.type === '自有' ? 'var(--success, #10b981)' : 'var(--accent2, #f59e0b)';
        const typeBg = carrier.type === '自有' ? 'rgba(16,185,129,0.1)' : 'rgba(245,158,11,0.1)';
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
                        <span class="cs-tag" style="background:rgba(31,58,95,0.1);color:var(--primary,#1F3A5F)">${shippingLine.code || ''}</span>
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

// ===== 海运费实时获取 =====
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
    const productType = productTypes[0] || '';  // 用第一个产品类型确定工厂和港口
    const destCountry = document.getElementById('destCountry')?.value || '';
    const boxTypes = getMultiSelectValues('boxTypeMulti');
    const boxType = boxTypes[0] || '40HQ';
    const weight = document.getElementById('weight')?.value || '15000';
    const boxCount = document.getElementById('boxes')?.value || '1';
    const cargoReady = document.getElementById('cargoReady')?.value || '';
    const shipSchedule = document.getElementById('shipSchedule')?.value || '';

    let routeInfo = null;
    let origin, destination;

    // Step 1: 通过后端知识库获取工厂→始发港 和 运抵国→目的港
    try {
        const routeUrl = new URL('/api/route-info', window.location.origin);
        routeUrl.searchParams.set('productType', productType);
        routeUrl.searchParams.set('destCountry', destCountry);
        if (cargoReady) routeUrl.searchParams.set('cargoReady', cargoReady);
        if (shipSchedule) routeUrl.searchParams.set('shipSchedule', shipSchedule);
        routeUrl.searchParams.set('boxType', boxType);

        const routeResp = await fetch(routeUrl.toString());
        const routeResult = await routeResp.json();

        if (routeResult.success && routeResult.data) {
            routeInfo = routeResult.data;
            origin = routeInfo.originPort;
            destination = routeInfo.destPort;
            console.log('[海运费] 路线查询成功:',
                routeInfo.factoryShort, '→', origin, '→', destination,
                '| 推荐航司:', routeInfo.recommendedShippingLine?.name || '无',
                '| 模式:', routeInfo.selectionMode);
        } else {
            // 回退：使用旧版默认映射
            console.warn('[海运费] 路线查询失败，回退到默认映射:', routeResult.error);
            const fallback = getOceanPortsByCountry(destCountry);
            origin = fallback.origin;
            destination = fallback.destination;
        }
    } catch (e) {
        // 后端不可用时回退
        console.warn('[海运费] 路线查询异常，回退到默认映射:', e.message);
        const fallback = getOceanPortsByCountry(destCountry);
        origin = fallback.origin;
        destination = fallback.destination;
    }

    // Step 2: 用正确的港口查询 Freightos 实时海运费
    try {
        const url = new URL('/api/freight-rate', window.location.origin);
        url.searchParams.set('origin', origin);
        url.searchParams.set('destination', destination);
        url.searchParams.set('boxType', boxType);
        url.searchParams.set('weight', weight);
        url.searchParams.set('quantity', Math.max(1, parseInt(boxCount) || 1));

        const resp = await fetch(url.toString(), { cache: 'no-store' });
        const result = await resp.json();

        if (result.success && result.data) {
            const d = result.data;

            // 更新价格UI
            document.getElementById('oceanMinRate').textContent = '$' + d.minRate.toLocaleString();
            document.getElementById('oceanMedianRate').textContent = '$' + d.medianRate.toLocaleString();
            document.getElementById('oceanMaxRate').textContent = '$' + d.maxRate.toLocaleString();

            // 航线信息
            document.getElementById('oceanRouteInfo').textContent =
                `${d.origin} → ${d.destination}`;

            // 转运天数（优先用后端route-info返回的船公司数据）
            if (routeInfo && routeInfo.transitDays) {
                document.getElementById('oceanTransitInfo').textContent =
                    `${routeInfo.transitDays}天转运 · ${routeInfo.cargoType}/${routeInfo.loadType}`;
            } else if (d.transitDays) {
                document.getElementById('oceanTransitInfo').textContent = `${d.transitDays}天转运`;
            } else {
                document.getElementById('oceanTransitInfo').textContent = '实时数据';
            }

            // 获取时间
            const fetchTime = d.fetchedAt
                ? new Date(d.fetchedAt).toLocaleString('zh-CN', {
                    month: '2-digit', day: '2-digit',
                    hour: '2-digit', minute: '2-digit'
                  })
                : '刚刚';
            document.getElementById('oceanFetchedAt').textContent =
                (d.stale ? '⚠️ 过期数据 · ' : d.cached ? '📌 缓存 · ' : '🌐 ') + fetchTime;

            // 如果数据过期，显示黄色警告
            if (d.stale) {
                document.getElementById('oceanTransitInfo').textContent =
                    (d.staleWarning || '数据已过期') + ' · 请手动确认';
            }

            // 更新推荐航司信息
            if (routeInfo && routeInfo.recommendedShippingLine) {
                const rec = routeInfo.recommendedShippingLine;
                const lineEl = document.getElementById('oceanShippingLine');
                if (lineEl) {
                    lineEl.textContent = `推荐航司: ${rec.name} (${rec.code}) · ${rec.transit_days}天 · ${rec.frequency}`;
                }
            }

            // 更新工厂和FCL/普货标签
            if (routeInfo) {
                const factoryEl = document.getElementById('oceanFactoryTag');
                if (factoryEl) {
                    factoryEl.textContent = `${routeInfo.factoryShort} · ${routeInfo.originPort}`;
                }
                const fclEl = document.getElementById('oceanFCLTag');
                if (fclEl) {
                    fclEl.textContent = `${routeInfo.cargoType} · ${routeInfo.isFCL ? 'FCL整箱' : 'LCL拼箱'}`;
                }
            }

            // 显示实时区域
            loadingEl.style.display = 'none';
            realtimeEl.style.display = 'block';

            // 自动将中位价填入海运费输入框（转换为CNY）
            const cny = Math.round(d.medianRate * 7.2 * 100) / 100;
            const oceanFeeInput = document.getElementById('oceanFee');
            const currentVal = parseFloat(oceanFeeInput.value);
            if (!oceanFeeInput.value || currentVal === 2500) {
                oceanFeeInput.value = cny;
                feeData.ocean.fee = cny;
                updateGrandTotal();
            }

            console.log('[海运费] 获取成功:', d.originCode, '→', d.destinationCode,
                `min=$${d.minRate}`, `median=$${d.medianRate}`, `max=$${d.maxRate}`,
                routeInfo ? `| 工厂=${routeInfo.factoryShort} 航司=${routeInfo.recommendedShippingLine?.code || 'N/A'}` : '');
        } else {
            throw new Error(result.error || '未知错误');
        }
    } catch (e) {
        console.error('[海运费] 获取失败:', e);
        loadingEl.style.display = 'none';
        realtimeEl.style.display = 'none';
        errorEl.style.display = 'flex';

        const msg = e.message || '';
        if (msg.includes('429') || msg.includes('限流') || msg.includes('Too Many Requests')) {
            errorDesc.textContent = 'Freightos API 限流中（免费API有请求频率限制），请等待1-2分钟后重试，或手动输入海运费';
        } else if (msg.includes('Failed to fetch') || msg.includes('NetworkError')) {
            errorDesc.textContent = '后端服务未启动或无法连接，请启动后端（python back/app.py）后重试';
        } else if (msg.includes('404') || msg.includes('not found')) {
            errorDesc.textContent = '后端代理接口不存在，请确认已重启后端服务';
        } else {
            errorDesc.textContent = msg || '获取失败，请手动输入海运费金额';
        }
    } finally {
        refreshBtn.classList.remove('loading');
    }
}

// 根据目的国获取标准航线港口（回退方案，仅在后端 /api/route-info 不可用时使用）
// 始发港按区域分配：华东/华中→上海，华北/山东→青岛，华南→深圳，海外→就近港口
function getOceanPortsByCountry(country) {
    const routeMap = {
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
