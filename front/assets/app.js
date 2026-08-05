/**
 * 物流运输路径智能优化系统 — 前端交互逻辑
 */

// ===== API 配置 =====
const API_BASE = 'http://localhost:5000';

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
});

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
            // 可以在此动态填充国家列表（当前使用静态HTML选项）
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
    // 获取表单数据
    const productType = document.getElementById('productType').value;

    const payload = {
        customer: document.getElementById('customer').value,
        productType: productType,
        destCountry: document.getElementById('destCountry').value,
        boxCount: parseInt(document.getElementById('boxes').value) || 0,
        weight: parseFloat(document.getElementById('weight').value) || 0,
        volume: parseFloat(document.getElementById('volume').value) || 0,
        cargoReady: document.getElementById('cargoReady').value,
        shipSchedule: document.getElementById('shipSchedule').value,
        transportPref: document.getElementById('transportPref').value,
        tradePref: document.getElementById('tradePref').value,
    };

    // 校验必填字段
    if (!payload.productType) {
        alert('请选择产品类型');
        return;
    }
    if (!payload.cargoReady || !payload.shipSchedule) {
        alert('请填写日期信息');
        return;
    }

    // 显示加载状态
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

    // 计算详情（可折叠）
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

    // 承运商信息
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

    // 船公司信息
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
