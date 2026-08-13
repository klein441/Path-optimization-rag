/**
 * 智能推荐结果面板
 */
import { store } from '../state.js';
import { calculateAllFees, applyResultToFeeData } from '../fees.js';
import { USD_TO_CNY } from '../constants.js';
import { fetchOceanFreightRate } from '../ocean.js';
import FeePanel from './FeePanel.js';

const TIMELINE_ICONS = {
    check: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M22 11.08V12a10 10 0 1 1-5.93-9.14"/></svg>',
    truck: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><rect x="1" y="3" width="15" height="13"/><polygon points="16 8 20 8 23 11 23 16 16 16 16 8"/><circle cx="5.5" cy="18.5" r="2.5"/><circle cx="18.5" cy="18.5" r="2.5"/></svg>',
    clock: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="10"/><polyline points="12 6 12 12 16 14"/></svg>',
    ship: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M3 18s1.5-2 4.5-2 4.5 2 9 2 4.5-2 4.5-2"/><path d="M21 12l-9-7-9 7"/><path d="M12 2l0 18"/></svg>',
    ocean: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M2 12h20"/><path d="M12 2a15.3 15.3 0 0 1 4 10 15.3 15.3 0 0 1-4 10 15.3 15.3 0 0 1-4-10 15.3 15.3 0 0 1 4-10z"/></svg>',
    dest: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M21 10c0 7-9 13-9 13s-9-6-9-13a9 9 0 0 1 18 0z"/><circle cx="12" cy="10" r="3"/></svg>',
};

export default {
    components: { FeePanel },
    data() {
        return { store: store };
    },
    computed: {
        primary() {
            return store.results.primary || {};
        },
        boxInfo() {
            const p = this.primary;
            const boxTypeCounts = p.boxTypeCounts || {};
            if (Object.keys(boxTypeCounts).length > 0) {
                return Object.entries(boxTypeCounts).map(([bt, qty]) => bt + '×' + qty).join(' + ');
            }
            const boxTypes = p.boxTypes || [p.boxType || '40HQ'];
            return Array.isArray(boxTypes) ? boxTypes.join(' + ') : boxTypes;
        },
        summaryItems() {
            const p = this.primary;
            const items = [];
            if (p.needFDA) items.push('FDA 合规');
            if (p.isOverseas) items.push('海外基地');
            items.push('综合评分 ' + (p.score || 0) + '/100');
            if (store.results.alternatives.length > 0) {
                items.push(store.results.alternatives.length + ' 个备选方案');
            }
            return items;
        },
        waitingInfo() {
            const p = this.primary;
            return (p.waitingDays && p.waitingDays > 0) ? ' + 等船 ' + p.waitingDays + '天' : '';
        },
        scoreLabel() {
            const score = this.primary.score || 0;
            return score >= 70 ? '优秀' : (score >= 50 ? '良好' : '一般');
        },
        effectiveTotalCny() {
            return calculateAllFees();
        },
        effectiveTotalUsd() {
            return Math.round(this.effectiveTotalCny / USD_TO_CNY);
        },
        shippingLines() {
            const sl = this.primary.shippingLines || {};
            return (sl.lines || []).slice(0, 5);
        },
        hasCarrierShipping() {
            const p = this.primary;
            return Boolean((p.carrier && p.carrier.recommended) || (p.shippingLine && p.shippingLine.name));
        },
        carrierTagStyle() {
            const type = (this.primary.carrier || {}).type;
            if (type === '自有') return 'background:rgba(22,163,74,0.1);color:var(--success,#16a34a)';
            return 'background:rgba(37,99,235,0.1);color:var(--accent,#2563EB)';
        },
        timelineSteps() {
            const p = this.primary;
            const timeline = p.timeline || {};
            const cargoReady = timeline.cargo_ready || p.cargoReady || '—';
            const etd = timeline.etd || p.etd || '—';
            const eta = timeline.eta || p.eta || '—';
            const waitingDays = timeline.waiting_days || p.waitingDays || 0;
            const steps = [
                { title: '货好时间', date: cargoReady, desc: '货物在工厂完成生产', done: true, icon: TIMELINE_ICONS.check },
                { title: '内陆运输', date: (timeline.inland_days || '?') + ' 天', desc: '工厂 → 始发港（拖车/铁路）', done: false, icon: TIMELINE_ICONS.truck },
            ];
            if (waitingDays > 0) {
                steps.push({ title: '等船期', date: waitingDays + ' 天', desc: '货物已到港，等待预定船期', done: false, icon: TIMELINE_ICONS.clock });
            }
            steps.push(
                { title: '预计离港 (ETD)', date: etd, desc: (timeline.ship_schedule || p.shipSchedule || '—') + ' 船期离港', done: false, icon: TIMELINE_ICONS.ship },
                { title: '海运在途', date: (timeline.ocean_days || '?') + ' 天', desc: '国际海运运输', done: false, icon: TIMELINE_ICONS.ocean },
                { title: '预计到港 (ETA)', date: eta, desc: '总周期 ' + (timeline.total_days || p.totalDays || '?') + ' 天（内陆' + (timeline.inland_days || '?') + '天' + (waitingDays > 0 ? ' + 等船' + waitingDays + '天' : '') + ' + 海运' + (timeline.ocean_days || '?') + '天）', done: false, icon: TIMELINE_ICONS.dest },
            );
            return steps;
        },
        reasoningText() {
            const d = store.results.data || {};
            return d.reasoning || '';
        },
        riskWarningText() {
            const d = store.results.data || {};
            return d.riskWarning || '';
        },
        suggestionText() {
            const d = store.results.data || {};
            return d.optimizationSuggestion || '';
        },
        hasReasoning() {
            return Boolean(this.reasoningText || this.riskWarningText || this.suggestionText);
        },
        reasoningTag() {
            const d = store.results.data || {};
            return d.source === 'llm' ? 'AI 生成' : '规则引擎';
        },
        routesCount() {
            return (store.results.allCandidates || []).length;
        },
    },
    methods: {
        usdText(n) {
            return '$' + Number(n).toLocaleString();
        },
        altCost(alt) {
            return alt.totalCostCny || (alt.cost && alt.cost.totalCny) || 0;
        },
        selectAlternative(alt) {
            if (!alt || !store.results.primary) return;
            const currentPrimary = store.results.primary;
            const alternatives = (store.results.alternatives || []).slice();
            if (alternatives.indexOf(alt) < 0) return;

            store.feeConfirmed = false;
            store.results.primary = alt;
            store.results.alternatives = [currentPrimary].concat(alternatives.filter(function (a) {
                return a !== alt;
            }));

            applyResultToFeeData({ primary: alt });
            store.ocean.realtime = false;
            store.ocean.loading = false;
            store.ocean.error = false;
            store.ocean.carriers = [];
            fetchOceanFreightRate();
            store.metaText = '已切换方案';
        },
        openAllRoutes() {
            try {
                localStorage.setItem('allRoutesData', JSON.stringify({
                    candidates: store.results.allCandidates || [],
                    primary: store.results.primary || {},
                    selection: {
                        factories: (store.results.data || {}).eligibleFactoryNames || [],
                        ports: (store.results.data || {}).selectedOriginPorts || [],
                    },
                }));
            } catch (e) {
                console.error('[全部路线] 数据保存失败:', e);
            }
            window.open('all-routes.html', '_blank');
        },
    },
    template: `
    <section class="panel result-panel">
      <div class="panel-header">
        <div class="icon-wrap">
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M12 2 2 7l10 5 10-5-10-5Z"/><path d="m2 17 10 5 10-5"/><path d="m2 12 10 5 10-5"/></svg>
        </div>
        <h2>智能推荐结果</h2>
        <span class="sub" id="resultMeta">{{ store.metaText }}</span>
      </div>
      <div class="result-body" id="resultBody">

        <!-- 空状态 -->
        <div class="empty-state" v-if="store.results.status === 'idle'">
          <div class="empty-icon">
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="10"/><path d="m16.24 7.76-2.12 6.36-6.36 2.12 2.12-6.36 6.36-2.12z"/></svg>
          </div>
          <h3>填写运输需求，获取智能推荐</h3>
          <p>系统将基于工厂产能、港口资源、运输成本、贸易条款等多维度数据，由大模型为您输出最优物流路径方案。</p>
          <div class="empty-features">
            <div class="empty-feature"><div class="ef-icon"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M3 9l9-7 9 7v11a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z"/></svg></div><span>工厂匹配</span></div>
            <div class="empty-feature"><div class="ef-icon"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M2 12h20"/><path d="M12 2a15.3 15.3 0 0 1 4 10 15.3 15.3 0 0 1-4 10 15.3 15.3 0 0 1-4-10 15.3 15.3 0 0 1 4-10z"/></svg></div><span>港口选择</span></div>
            <div class="empty-feature"><div class="ef-icon"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><line x1="12" y1="1" x2="12" y2="23"/><path d="M17 5H9.5a3.5 3.5 0 0 0 0 7h5a3.5 3.5 0 0 1 0 7H6"/></svg></div><span>成本测算</span></div>
            <div class="empty-feature"><div class="ef-icon"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="10"/><polyline points="12 6 12 12 16 14"/></svg></div><span>时效预估</span></div>
          </div>
        </div>

        <!-- 加载状态 -->
        <div class="loading-state" v-else-if="store.results.status === 'loading'">
          <div class="loading-spinner"></div>
          <h3>正在生成最优路径方案</h3>
          <p>系统正在分析工厂产能、港口资源、运输成本和时效...</p>
        </div>

        <!-- 错误状态 -->
        <div class="empty-state" style="min-height:400px" v-else-if="store.results.status === 'error'">
          <div class="empty-icon" style="background:linear-gradient(135deg,rgba(220,38,38,0.08),rgba(220,38,38,0.05))">
            <svg viewBox="0 0 24 24" fill="none" stroke="#dc2626" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="10"/><line x1="15" y1="9" x2="9" y2="15"/><line x1="9" y1="9" x2="15" y2="15"/></svg>
          </div>
          <h3>请求失败</h3>
          <p>{{ store.results.errorMsg }}</p>
        </div>

        <!-- 推荐结果 -->
        <div class="results-container" v-else-if="store.results.status === 'success' && store.results.primary">

          <!-- 路线信息条 -->
          <div class="route-info-banner">
            <div class="rib-item"><div class="rib-label">🏭 发货工厂</div><div class="rib-value">{{ primary.factoryShort || primary.factory || '—' }}</div></div>
            <div class="rib-arrow">→</div>
            <div class="rib-item"><div class="rib-label">⚓ 始发港</div><div class="rib-value">{{ primary.departurePort || '—' }}</div></div>
            <div class="rib-arrow">→</div>
            <div class="rib-item"><div class="rib-label">📍 终到港</div><div class="rib-value">{{ primary.destPort || '—' }}</div></div>
            <div class="rib-divider"></div>
            <div class="rib-item"><div class="rib-label">📋 贸易条款</div><div class="rib-value">{{ primary.tradeTerm || 'FOB' }}</div></div>
            <div class="rib-item"><div class="rib-label">📦 柜型/数量</div><div class="rib-value">{{ boxInfo }}</div></div>
          </div>

          <!-- 路线可视化 -->
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
                <div class="route-node-label">{{ primary.factoryShort || primary.factory || '未知工厂' }}</div>
                <div class="route-node-sub">{{ primary.region || '' }}</div>
              </div>
              <div class="route-arrow">
                <div class="ra-line"></div>
                <div class="ra-label">陆运 {{ primary.inlandDays || '?' }}天</div>
              </div>
              <div class="route-node">
                <div class="route-node-icon port">
                  <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M2 12h20"/><path d="M12 2a15.3 15.3 0 0 1 4 10 15.3 15.3 0 0 1-4 10 15.3 15.3 0 0 1-4-10 15.3 15.3 0 0 1 4-10z"/></svg>
                </div>
                <div class="route-node-label">{{ primary.departurePort || '未指定' }}</div>
                <div class="route-node-sub">{{ primary.tradeTerm || 'FOB' }}</div>
              </div>
              <div class="route-arrow">
                <div class="ra-line"></div>
                <div class="ra-label">海运 {{ primary.oceanDays || '?' }}天</div>
              </div>
              <div class="route-node">
                <div class="route-node-icon dest">
                  <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M21 10c0 7-9 13-9 13s-9-6-9-13a9 9 0 0 1 18 0z"/><circle cx="12" cy="10" r="3"/></svg>
                </div>
                <div class="route-node-label">{{ primary.destPort || '未指定' }}</div>
                <div class="route-node-sub">目的港</div>
              </div>
            </div>
          </div>

          <!-- 费用信息确认面板（含船公司合约报价区） -->
          <FeePanel />

          <!-- 摘要横幅 -->
          <div class="summary-banner">
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M22 11.08V12a10 10 0 1 1-5.93-9.14"/><polyline points="22 4 12 14.01 9 11.01"/></svg>
            <span>预计 <b>{{ primary.totalDays || 0 }}</b> 天完成全部运输流程 · {{ summaryItems.join(' · ') }}</span>
          </div>

          <!-- 关键指标卡片 -->
          <div class="rec-grid">
            <div class="rec-card">
              <div class="rec-card-label">
                <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><line x1="12" y1="1" x2="12" y2="23"/><path d="M17 5H9.5a3.5 3.5 0 0 0 0 7h5a3.5 3.5 0 0 1 0 7H6"/></svg>
                预计总费用
              </div>
              <div class="rec-card-value mono">¥{{ effectiveTotalCny.toLocaleString() }}</div>
              <div class="rec-card-sub">约 {{ usdText(effectiveTotalUsd) }} USD</div>
            </div>
            <div class="rec-card">
              <div class="rec-card-label">
                <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="10"/><polyline points="12 6 12 12 16 14"/></svg>
                运输周期
              </div>
              <div class="rec-card-value">{{ primary.totalDays || '?' }} 天</div>
              <div class="rec-card-sub">内陆 {{ primary.inlandDays || '?' }}天{{ waitingInfo }} + 海运 {{ primary.oceanDays || '?' }}天</div>
            </div>
            <div class="rec-card">
              <div class="rec-card-label">
                <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><polygon points="12 2 15.09 8.26 22 9.27 17 14.14 18.18 21.02 12 17.77 5.82 21.02 7 14.14 2 9.27 8.91 8.26 12 2"/></svg>
                综合评分
              </div>
              <div class="rec-card-value">{{ primary.score || 0 }}<span style="font-size:0.8rem;color:var(--muted)">/100</span></div>
              <div class="rec-card-sub">{{ scoreLabel }}</div>
            </div>
          </div>

          <!-- 承运商和船公司 -->
          <div class="carrier-shipping-section" v-if="hasCarrierShipping">
            <div class="cs-grid">
              <div class="cs-card" v-if="primary.carrier && primary.carrier.recommended">
                <div class="cs-card-header">
                  <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" style="width:16px;height:16px"><rect x="1" y="3" width="15" height="13"/><polygon points="16 8 20 8 23 11 23 16 16 16 16 8"/><circle cx="5.5" cy="18.5" r="2.5"/><circle cx="18.5" cy="18.5" r="2.5"/></svg>
                  承运商（车队）
                </div>
                <div class="cs-card-body">
                  <div class="cs-primary">
                    <span class="cs-name">{{ primary.carrier.recommended }}</span>
                    <span class="cs-tag" :style="carrierTagStyle">{{ primary.carrier.type }}</span>
                  </div>
                  <div class="cs-meta">
                    <span>历史 {{ primary.carrier.count || 0 }} 次</span>
                    <span>运输方式：{{ primary.carrier.mode || '直拖' }}</span>
                    <span>自有车队占比 {{ primary.carrier.self_owned_ratio || 0 }}%</span>
                  </div>
                  <div class="cs-alts" v-if="primary.carrier.alternatives && primary.carrier.alternatives.length">
                    <span class="cs-alts-label">备选车队：</span>
                    <span class="cs-alt-tag" v-for="a in primary.carrier.alternatives" :key="a.carrier">{{ a.carrier }}（{{ a.type }}，{{ a.count }}次）</span>
                  </div>
                </div>
              </div>
              <div class="cs-card" v-if="primary.shippingLine && primary.shippingLine.name">
                <div class="cs-card-header">
                  <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" style="width:16px;height:16px"><path d="M3 18s1.5-2 4.5-2 4.5 2 9 2 4.5-2 4.5-2"/><path d="M21 12l-9-7-9 7"/><path d="M12 2l0 18"/></svg>
                  船公司
                </div>
                <div class="cs-card-body">
                  <div class="cs-primary">
                    <span class="cs-name">{{ primary.shippingLine.name }}</span>
                    <span class="cs-tag" style="background:rgba(37,99,235,0.1);color:var(--accent,#2563EB)">{{ primary.shippingLine.code || '' }}</span>
                  </div>
                  <div class="cs-meta">
                    <span>航程 {{ primary.shippingLine.transit_days || '?' }} 天</span>
                    <span>{{ primary.shippingLine.frequency || '' }}</span>
                  </div>
                  <div class="cs-advantage">{{ primary.shippingLine.advantage || '' }}</div>
                  <div class="cs-alts" v-if="shippingLines.length > 1">
                    <span class="cs-alts-label">其他可选船公司：</span>
                    <span class="cs-alt-tag" v-for="l in shippingLines.slice(1)" :key="l.name">{{ l.name }}（{{ l.transit_days }}天）</span>
                  </div>
                </div>
              </div>
            </div>
          </div>

          <!-- 时间线 -->
          <div class="timeline-section">
            <div class="timeline-header">
              <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="10"/><polyline points="12 6 12 12 16 14"/></svg>
              运输时间线
            </div>
            <div class="timeline">
              <div class="timeline-item" v-for="(step, idx) in timelineSteps" :key="idx">
                <div class="timeline-dot" :class="{ done: step.done }" v-html="step.icon"></div>
                <div class="timeline-content">
                  <div class="timeline-title">{{ step.title }}</div>
                  <div class="timeline-date">{{ step.date }}</div>
                  <div class="timeline-desc">{{ step.desc }}</div>
                </div>
              </div>
            </div>
          </div>

          <!-- AI 推荐理由 -->
          <div class="reasoning-section" v-if="hasReasoning">
            <div class="reasoning-header">
              <div class="ai-badge">
                <svg viewBox="0 0 24 24" fill="none" stroke="#fff" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><polygon points="12 2 15.09 8.26 22 9.27 17 14.14 18.18 21.02 12 17.77 5.82 21.02 7 14.14 2 9.27 8.91 8.26 12 2"/></svg>
              </div>
              <h3>智能分析与推荐理由</h3>
              <span class="tag">{{ reasoningTag }}</span>
            </div>
            <div class="reasoning-body">
              <p v-if="reasoningText"><strong>推荐理由：</strong>{{ reasoningText }}</p>
              <p v-if="riskWarningText" style="color:var(--warning)"><strong>⚠ 风险提示：</strong>{{ riskWarningText }}</p>
              <p v-if="suggestionText" style="color:var(--accent2-dark)"><strong>💡 优化建议：</strong>{{ suggestionText }}</p>
            </div>
          </div>

          <!-- 备选方案 -->
          <div class="alt-section" v-if="store.results.alternatives.length">
            <div class="alt-header">
              <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><line x1="8" y1="6" x2="21" y2="6"/><line x1="8" y1="12" x2="21" y2="12"/><line x1="8" y1="18" x2="21" y2="18"/><line x1="3" y1="6" x2="3.01" y2="6"/><line x1="3" y1="12" x2="3.01" y2="12"/><line x1="3" y1="18" x2="3.01" y2="18"/></svg>
              备选方案
              <span class="count">{{ store.results.alternatives.length }} 个方案</span>
            </div>
            <div class="alt-list">
              <div class="alt-card" v-for="(alt, idx) in store.results.alternatives" :key="idx" @click="selectAlternative(alt, idx)">
                <div class="alt-rank">{{ idx + 2 }}</div>
                <div class="alt-info">
                  <div class="alt-route">
                    <span>{{ alt.factoryShort || alt.factory }}</span>
                    <span class="sep">→</span>
                    <span>{{ alt.departurePort || alt.origin_port || '—' }}</span>
                    <span class="sep">→</span>
                    <span>{{ alt.destPort || alt.dest_port || '—' }}</span>
                  </div>
                  <div class="alt-meta">
                    <span>📋 {{ alt.tradeTerm || 'FOB' }}</span>
                    <span>🚢 {{ alt.oceanDays || alt.ocean_days || '?' }}天海运</span>
                    <span>⏱ {{ alt.totalDays || 0 }}天</span>
                    <span v-if="alt.carrier && alt.carrier.recommended">🚛 {{ alt.carrier.recommended }}</span>
                    <span v-if="alt.shippingLine && alt.shippingLine.name">⚓ {{ alt.shippingLine.name }}</span>
                  </div>
                </div>
                <div class="alt-cost">
                  <b>¥{{ altCost(alt).toLocaleString() }}</b>
                  <span>综合评分 {{ alt.score || 0 }}</span>
                </div>
              </div>
            </div>
          </div>

          <!-- 全部路线价格对比入口（页面最底部） -->
          <div class="all-routes-entry" v-if="routesCount > 0">
            <button type="button" class="all-routes-btn" @click="openAllRoutes">
              <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" style="width:16px;height:16px"><path d="M3 3v18h18"/><path d="m19 9-5 5-4-4-3 3"/></svg>
              全部路线价格对比
              <span class="count">{{ routesCount }} 条路线</span>
            </button>
          </div>

        </div>
      </div>
    </section>
    `,
};
