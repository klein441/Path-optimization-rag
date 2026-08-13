/**
 * 结果页费用信息确认面板（含船公司合约报价区）
 * 海运费区块默认展开，挂载后自动加载合约报价 —— 保证船公司报价区直接可见。
 */
import { reactive } from '../../vendor/vue.esm-browser.prod.js';
import { store } from '../state.js';
import { TRANSPORT_MODE_FREIGHT } from '../constants.js';
import { formatFee, autoEnableICS2ForEurope, showNotification, isFTradeTerm } from '../utils.js';
import { initLandFees, calculateTollFee, getSeaManagerTotal, getOtherTotal, calculateAllFees, buildConfirmedFeeItems } from '../fees.js';
import { fetchPortMiscFee, apiConfirmFees } from '../api.js';
import { fetchOceanFreightRate, selectPortMiscCarrier, selectLandCarrier } from '../ocean.js';
import OceanQuotes from './OceanQuotes.js';

export default {
    components: { OceanQuotes },
    data() {
        return {
            store: store,
            TRANSPORT_MODE_FREIGHT: TRANSPORT_MODE_FREIGHT,
            sections: reactive({ land: false, seaManager: false, portMisc: false, ocean: false, other: false }),
        };
    },
    computed: {
        modeConf() {
            return TRANSPORT_MODE_FREIGHT[this.store.feeData.land.transportMode] || TRANSPORT_MODE_FREIGHT.direct;
        },
        insideVisible() {
            const p = this.store.feeData.land.factoryProvince;
            return p === '江西' || p === '安徽';
        },
        landTotal() {
            const l = this.store.feeData.land;
            return l.baseFreight + l.tollFee + l.insideLoadFee;
        },
        seaManagerTotal() { return getSeaManagerTotal(); },
        otherTotal() { return getOtherTotal(); },
        totalFees() { return calculateAllFees(); },
        isFTerm() {
            const term = (store.results.primary && store.results.primary.tradeTerm) || store.form.tradePref || '';
            return isFTradeTerm(term);
        },
    },
    mounted() {
        autoEnableICS2ForEurope();
        setTimeout(() => {
            if (!this.isFTerm && !store.ocean.realtime && !store.ocean.loading) {
                fetchOceanFreightRate();
            }
            const primary = store.results.primary;
            const originPort = (primary && primary.departurePort) ? primary.departurePort : '';
            let tradeTerm = (primary && primary.tradeTerm) ? primary.tradeTerm : '';
            if (tradeTerm === 'auto' || tradeTerm === '智能推荐') tradeTerm = '';
            if (originPort) {
                fetchPortMiscFee(originPort, tradeTerm, store.form.boxTypes.slice());
            }
        }, 400);
    },
    methods: {
        formatFee: formatFee,
        toggleSection(name) {
            const wasOpen = this.sections[name];
            this.sections[name] = !this.sections[name];
            if (!wasOpen && name === 'ocean' && !this.isFTerm && !store.ocean.realtime && !store.ocean.loading) {
                fetchOceanFreightRate();
            }
        },
        onTransportModeChange() {
            const l = store.feeData.land;
            initLandFees(l.factoryProvince, l.transportMode, l.factoryName, l.originPort);
            if (l.transportMode === 'factorySelf') {
                calculateTollFee();
            }
        },
        onManifestModeChange() {
            const sm = store.feeData.seaManager;
            if (sm.manifestMode !== 'custom') {
                sm.manifestFee = parseFloat(sm.manifestMode) || 0;
            }
        },
        addOtherRow() {
            store.feeData.other.push({ name: '', amount: 0 });
        },
        removeOther(idx) {
            store.feeData.other.splice(idx, 1);
        },
        refresh() {
            fetchOceanFreightRate();
        },
        selectMiscCarrier(carrier) {
            selectPortMiscCarrier(carrier);
        },
        selectLandCarrierHandler(carrier) {
            selectLandCarrier(carrier);
        },
        async confirmFees() {
            const oceanCarrier = store.feeData.ocean.selectedCarrier;
            if (!this.isFTerm && oceanCarrier && oceanCarrier.isValid === false) {
                showNotification('当前海运费合约已过期，请选择有效合约后再确认');
                return;
            }
            store.feeConfirmed = true;
            const total = calculateAllFees();
            if (store.lastSubmitPayload) {
                try {
                    await apiConfirmFees({
                        payload: store.lastSubmitPayload,
                        total: total,
                        items: buildConfirmedFeeItems(),
                    });
                } catch (e) {
                    console.warn('[费用确认] 数据库同步失败:', e.message);
                }
            }
            showNotification('费用信息已确认，最终费用¥' + formatFee(total));
        },
        unlockFees() {
            store.feeConfirmed = false;
        },
        onTollToggle(ev) {
            store.feeData.land.tollEnabled = ev.target.checked;
        },
        onInsideToggle(ev) {
            store.feeData.land.insideLoadEnabled = ev.target.checked;
        },
    },
    template: `
        <div id="feePanelInResults" class="fee-panel-in-results">
          <h3 style="font-size:0.9rem;font-weight:700;color:var(--accent);margin-bottom:0.6rem;display:flex;align-items:center;gap:0.4rem"><span>💰</span> 费用信息确认</h3>

          <div class="fee-confirmed-banner" v-if="store.feeConfirmed">
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" style="width:22px;height:22px"><path d="M22 11.08V12a10 10 0 1 1-5.93-9.14"/><polyline points="22 4 12 14.01 9 11.01"/></svg>
            <div>
              <div class="fee-confirmed-title">费用信息已确认</div>
              <div class="fee-confirmed-total">最终费用总额 ¥{{ formatFee(totalFees) }}</div>
            </div>
          </div>

          <!-- 陆运费 section（含承运商推荐） -->
          <div class="fee-section ocean ocean-body" :class="{ open: sections.land }" data-fee-group="land">
            <div class="fee-section-header" @click="toggleSection('land')">
              <div class="fee-section-icon"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><rect x="1" y="3" width="15" height="13"/><polygon points="16 8 20 8 23 11 23 16 16 16 16 8"/><circle cx="5.5" cy="18.5" r="2.5"/><circle cx="18.5" cy="18.5" r="2.5"/></svg></div>
              <div class="fee-section-title">工厂到起运港拖车费</div>
              <div class="fee-section-summary">¥{{ formatFee(landTotal) }}</div>
              <svg class="fee-section-arrow" viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><polyline points="6 4 10 8 6 12"/></svg>
            </div>
            <div class="fee-section-body" style="padding:12px">
              <div class="fee-item">
                <div class="fee-item-label">运输方式</div>
                <select class="fee-select" v-model="store.feeData.land.transportMode" @change="onTransportModeChange" :disabled="store.feeConfirmed">
                  <option v-for="m in ['direct','seaRail','factorySelf','landToWater']" :key="m" :value="m">{{ (TRANSPORT_MODE_FREIGHT[m] || {}).label || m }}</option>
                </select>
              </div>
              <!-- 加载中 -->
              <div class="ocean-loading" v-show="store.feeData.land.loading">
                <div class="ocean-spinner"></div>
                <span>正在从拖车费表加载报价...</span>
              </div>
              <!-- 查询失败 — 降级为手工输入 -->
              <template v-if="!store.feeData.land.loading && store.feeData.land.error">
                <div class="fee-item">
                  <div class="fee-item-label">陆运费</div>
                  <input type="number" class="fee-item-input" v-model.number="store.feeData.land.baseFreight" step="0.1" min="0" :disabled="store.feeConfirmed">
                  <span class="fee-item-unit">元</span>
                </div>
              </template>
              <!-- 匹配成功 — 承运商推荐展示 -->
              <div v-show="store.feeData.land.carriers.length > 0">
                <!-- 承运商报价卡片 -->
                <div style="margin-top:12px">
                  <div style="font-weight:600;font-size:13px;color:#334155;margin-bottom:10px;display:flex;align-items:center;gap:6px">
                    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" style="width:14px;height:14px;color:var(--accent)"><path d="M16 4h2a2 2 0 0 1 2 2v14a2 2 0 0 1-2 2H6a2 2 0 0 1-2-2V6a2 2 0 0 1 2-2h2"/><rect x="8" y="2" width="8" height="4" rx="1" ry="1"/></svg>
                    各承运商拖车费报价
                  </div>
                  <div class="ocean-quotes-grid">
                    <div v-for="(c, idx) in store.feeData.land.carriers" :key="c.carrier"
                         class="ocean-quote-card"
                         :class="{ cheapest: idx === 0, selected: store.feeData.land.selectedCarrier && store.feeData.land.selectedCarrier.carrier === c.carrier, disabled: store.feeConfirmed }"
                         @click="selectLandCarrierHandler(c)">
                      <div class="ocean-quote-card-top">
                        <div class="ocean-quote-carrier"><span v-if="idx === 0" class="star-icon">⭐</span>{{ c.carrier }}</div>
                        <div class="ocean-quote-price">¥{{ c.landFreightMedian }}<span style="font-size:11px;font-weight:400;color:#94a3b8">/柜</span></div>
                      </div>
                      <div class="ocean-quote-card-meta">
                        <span>样本{{ c.sampleCount || 0 }}</span>
                        <span class="meta-sep" v-if="c.tollFreightMedian > 0">·</span>
                        <span v-if="c.tollFreightMedian > 0">高速费¥{{ c.tollFreightMedian }}</span>
                        <span class="meta-sep" v-if="c.boxType">·</span>
                        <span v-if="c.boxType">{{ c.boxType }}</span>
                      </div>
                    </div>
                  </div>
                </div>
              </div>
              <!-- 陆运费/高速费金额 -->
              <div class="fee-item" v-show="store.feeData.land.carriers.length === 0 && !store.feeData.land.error && !store.feeData.land.loading">
                <div class="fee-item-label">陆运费</div>
                <input type="number" class="fee-item-input" v-model.number="store.feeData.land.baseFreight" step="0.1" min="0" :disabled="store.feeConfirmed">
                <span class="fee-item-unit">元</span>
              </div>
              <div class="fee-item" v-show="modeConf.hasToll">
                <div class="fee-item-label">高速费</div>
                <div class="toggle-wrap">
                  <label class="toggle-switch"><input type="checkbox" :checked="store.feeData.land.tollEnabled" @change="onTollToggle($event)" :disabled="store.feeConfirmed"><span class="toggle-slider"></span></label>
                  <span class="toggle-label">产生</span>
                </div>
                <input type="number" class="fee-item-input small" v-model.number="store.feeData.land.tollFee" step="0.1" min="0" :disabled="store.feeConfirmed">
                <span class="fee-item-unit">元</span>
              </div>
              <div class="fee-item" v-show="insideVisible">
                <div class="fee-item-label">内装费 <span class="info-badge">江西/安庆基地</span></div>
                <div class="toggle-wrap">
                  <label class="toggle-switch"><input type="checkbox" :checked="store.feeData.land.insideLoadEnabled" @change="onInsideToggle($event)" :disabled="store.feeConfirmed"><span class="toggle-slider"></span></label>
                  <span class="toggle-label">需要</span>
                </div>
                <input type="number" class="fee-item-input small" v-model.number="store.feeData.land.insideLoadFee" step="0.1" min="0" :disabled="store.feeConfirmed">
                <span class="fee-item-unit">元</span>
              </div>
            </div>
          </div>

          <!-- 海管家 section -->
          <div class="fee-section ocean ocean-body" :class="{ open: sections.seaManager }" data-fee-group="seaManager">
            <div class="fee-section-header" @click="toggleSection('seaManager')">
              <div class="fee-section-icon"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M3 18s1.5-2 4.5-2 4.5 2 9 2 4.5-2 4.5-2"/><path d="M21 12l-9-7-9 7"/><path d="M12 2l0 18"/></svg></div>
              <div class="fee-section-title">海管家费用</div>
              <div class="fee-section-summary">¥{{ formatFee(seaManagerTotal) }}</div>
              <svg class="fee-section-arrow" viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><polyline points="6 4 10 8 6 12"/></svg>
            </div>
            <div class="fee-section-body ocean-body">
              <div class="fee-item">
                <div class="fee-item-label">舱单费 <span class="info-badge">元/柜</span></div>
                <select class="fee-select" id="fpManifestSelect" v-model="store.feeData.seaManager.manifestMode" @change="onManifestModeChange" :disabled="store.feeConfirmed">
                  <option v-for="v in [55,25,35,80]" :key="v" :value="String(v)">{{ v }}</option>
                  <option value="custom">自定义</option>
                </select>
                <input type="number" class="fee-item-input small" id="fpManifestCustom" placeholder="自定义" step="0.1" min="0" v-if="store.feeData.seaManager.manifestMode === 'custom'" v-model.number="store.feeData.seaManager.manifestFee" :disabled="store.feeConfirmed">
                <span class="fee-item-unit">元</span>
              </div>
              <div class="fee-item">
                <div class="fee-item-label">VGM费 <span class="info-badge">元/柜</span></div>
                <input type="number" class="fee-item-input" id="fpVgmFee" v-model.number="store.feeData.seaManager.vgmFee" step="0.1" min="0" :disabled="store.feeConfirmed">
                <span class="fee-item-unit">元</span>
              </div>
              <div class="fee-item">
                <div class="fee-item-label">ICS2费 <span class="info-badge">欧盟/欧洲经济区</span></div>
                <span class="fee-item-value" style="font-size:0.9rem;font-weight:600;color:var(--ink)" v-if="store.feeData.seaManager.ics2Enabled">¥70</span>
                <span class="fee-item-value" style="font-size:0.9rem;font-weight:600;color:var(--muted)" v-else>不适用</span>
                <span class="fee-item-unit" v-if="store.feeData.seaManager.ics2Enabled">元</span>
              </div>
            </div>
          </div>

          <!-- 港杂费 section（含承运商推荐） -->
          <div class="fee-section ocean ocean-body" :class="{ open: sections.portMisc }" data-fee-group="portMisc">
            <div class="fee-section-header" @click="toggleSection('portMisc')">
              <div class="fee-section-icon"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M2 12h20"/><path d="M12 2a15.3 15.3 0 0 1 4 10 15.3 15.3 0 0 1-4 10 15.3 15.3 0 0 1-4-10 15.3 15.3 0 0 1 4-10z"/><circle cx="12" cy="12" r="3"/></svg></div>
              <div class="fee-section-title">港杂费</div>
              <div class="fee-section-summary">¥{{ formatFee(store.feeData.portMisc.fee) }}</div>
              <svg class="fee-section-arrow" viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><polyline points="6 4 10 8 6 12"/></svg>
            </div>
            <div class="fee-section-body" style="padding:12px">
              <!-- 加载中 -->
              <div class="ocean-loading" v-show="store.feeData.portMisc.loading">
                <div class="ocean-spinner"></div>
                <span>正在从标准表加载港杂费报价...</span>
              </div>
              <!-- 查询失败 -->
              <div class="ocean-error" v-show="store.feeData.portMisc.error">
                <div class="ocean-error-icon">
                  <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="10"/><line x1="15" y1="9" x2="9" y2="15"/><line x1="9" y1="9" x2="15" y2="15"/></svg>
                </div>
                <div>
                  <div class="ocean-error-title">港杂费标准未匹配</div>
                  <div class="ocean-error-desc">请检查始发港 / 贸易条款 / 柜型是否在标准表范围内</div>
                </div>
              </div>
              <!-- 标准表匹配成功 — 承运商推荐展示 -->
              <div v-show="store.feeData.portMisc.carriers.length > 0">
                <!-- 各承运商报价卡片 -->
                <div style="margin-top:12px">
                  <div style="font-weight:600;font-size:13px;color:#334155;margin-bottom:10px;display:flex;align-items:center;gap:6px">
                    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" style="width:14px;height:14px;color:var(--accent)"><path d="M16 4h2a2 2 0 0 1 2 2v14a2 2 0 0 1-2 2H6a2 2 0 0 1-2-2V6a2 2 0 0 1 2-2h2"/><rect x="8" y="2" width="8" height="4" rx="1" ry="1"/></svg>
                    各承运商港杂费报价
                  </div>
                  <div class="ocean-quotes-grid">
                    <div v-for="(c, idx) in store.feeData.portMisc.carriers" :key="c.carrier"
                         class="ocean-quote-card"
                         :class="{ cheapest: idx === 0, selected: store.feeData.portMisc.selectedCarrier && store.feeData.portMisc.selectedCarrier.carrier === c.carrier, disabled: store.feeConfirmed }"
                         @click="selectMiscCarrier(c)">
                      <div class="ocean-quote-card-top">
                        <div class="ocean-quote-carrier"><span v-if="idx === 0" class="star-icon">⭐</span>{{ c.carrier }}</div>
                        <div class="ocean-quote-price">¥{{ c.recommendedFee }}<span style="font-size:11px;font-weight:400;color:#94a3b8">/柜</span></div>
                      </div>
                      <div class="ocean-quote-card-meta">
                        <span class="valid-badge ok">{{ c.dataLevel || '—' }}</span>
                        <span class="meta-sep">·</span>
                        <span>样本{{ c.sampleCount || 0 }}</span>
                        <span class="meta-sep">·</span>
                        <span>¥{{ c.lowerBound }}~¥{{ c.upperBound }}</span>
                      </div>
                    </div>
                  </div>
                </div>
                <!-- 港杂费合计（单柜费率 × 柜数） -->
                <div class="ocean-total-row" style="margin-top:12px">
                  <span class="ocean-total-label">港杂费合计</span>
                  <span class="ocean-total-value-wrap">
                    <input type="number" class="ocean-total-input" id="fpPortMiscFee" v-model.number="store.feeData.portMisc.fee" step="0.1" min="0" :disabled="store.feeConfirmed">
                    <span class="ocean-total-unit">元</span>
                  </span>
                </div>
              </div>
              <!-- 降级：无承运商数据时保持手工输入 -->
              <div v-show="!store.feeData.portMisc.loading && !store.feeData.portMisc.error && store.feeData.portMisc.carriers.length === 0">
                <div class="fee-item">
                  <div class="fee-item-label">港杂费合计</div>
                  <input type="number" class="fee-item-input" v-model.number="store.feeData.portMisc.fee" step="0.1" min="0" :disabled="store.feeConfirmed">
                  <span class="fee-item-unit">元</span>
                </div>
              </div>
            </div>
          </div>

          <!-- 海运费 section — 合约报价（默认展开） -->
          <div class="fee-section ocean ocean-body" :class="{ open: sections.ocean }" data-fee-group="ocean" v-if="!isFTerm">
            <div class="fee-section-header" @click="toggleSection('ocean')">
              <div class="fee-section-icon ocean-icon"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M3 18s1.5-2 4.5-2 4.5 2 9 2 4.5-2 4.5-2"/><path d="M21 12l-9-7-9 7"/><path d="M12 2l0 18"/></svg></div>
              <div class="fee-section-title">海运费</div>
              <div class="fee-section-summary" id="fpOceanFeeSummary">¥{{ formatFee(store.feeData.ocean.fee) }}</div>
              <svg class="fee-section-arrow" viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><polyline points="6 4 10 8 6 12"/></svg>
            </div>
            <div class="fee-section-body ocean-body">

              <!-- 加载中 -->
              <div class="ocean-loading" id="fpOceanLoading" v-show="store.ocean.loading">
                <div class="ocean-spinner"></div>
                <span>正在从合约表加载海运费报价...</span>
              </div>

              <!-- 加载失败 -->
              <div class="ocean-error" id="fpOceanError" v-show="store.ocean.error">
                <div class="ocean-error-icon">
                  <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="10"/><line x1="15" y1="9" x2="9" y2="15"/><line x1="9" y1="9" x2="15" y2="15"/></svg>
                </div>
                <div>
                  <div class="ocean-error-title">合约报价未匹配</div>
                  <div class="ocean-error-desc" id="fpOceanErrorDesc">{{ store.ocean.errorDesc }}</div>
                </div>
                <button class="ocean-retry" @click="refresh">重试</button>
              </div>

              <!-- 合约报价成功展示 -->
              <div class="ocean-realtime" id="fpOceanRealtime" v-show="store.ocean.realtime">
                <div class="ocean-realtime-header">
                  <div class="ocean-realtime-source">
                    <span class="live-dot" style="background:#10b981;box-shadow:0 0 8px #10b981"></span>
                    <span>合约报价 · 海运费参考标准.xlsx</span>
                  </div>
                  <div class="ocean-realtime-actions">
                    <button class="ocean-refresh" id="fpOceanRefreshBtn" @click="refresh" title="重新加载合约报价" :disabled="store.feeConfirmed">
                      <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><polyline points="23 4 23 10 17 10"/><path d="M20.49 15a9 9 0 1 1-2.12-9.36L23 10"/></svg>
                      <span>刷新</span>
                    </button>
                  </div>
                </div>
                <div class="ocean-realtime-rates">
                  <div class="ocean-rate-item primary">
                    <div class="ocean-rate-value" id="fpOceanMedianRate">{{ store.ocean.medianRateText }}</div>
                  </div>
                </div>
                <div class="ocean-realtime-meta">
                  <span id="fpOceanRouteInfo">{{ store.ocean.routeInfoText }}</span><span class="dot">·</span>
                  <span id="fpOceanTransitInfo">{{ store.ocean.transitInfoText }}</span><span class="dot">·</span>
                  <span id="fpOceanFetchedAt">{{ store.ocean.fetchedAtText }}</span>
                </div>
                <div class="ocean-realtime-tags">
                  <span class="ocean-tag factory-tag" id="fpOceanFactoryTag">{{ store.ocean.factoryTagText }}</span>
                  <span class="ocean-tag fcl-tag">普货 · FCL整柜</span>
                  <span class="ocean-tag carrier-tag" id="fpOceanShippingLine">{{ store.ocean.shippingLineText }}</span>
                </div>
                <div class="ocean-realtime-quotes" id="fpOceanQuotesList" v-show="store.ocean.carriers.length">
                  <div style="font-weight:600;font-size:13px;color:#334155;margin-bottom:10px;display:flex;align-items:center;gap:6px">
                    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" style="width:14px;height:14px;color:var(--accent)"><rect x="3" y="3" width="18" height="18" rx="2" ry="2"/><line x1="3" y1="9" x2="21" y2="9"/><line x1="9" y1="21" x2="9" y2="9"/></svg>
                    各船公司合约报价
                  </div>
                  <div id="fpOceanQuotesGrid" style="overflow-x:auto"><OceanQuotes /></div>
                </div>
              </div>

              <!-- 海运费合计 -->
              <div class="ocean-total-row">
                <span class="ocean-total-label">海运费合计</span>
                <span class="ocean-total-value-wrap">
                  <input type="number" class="ocean-total-input" id="fpOceanFee" v-model.number="store.feeData.ocean.fee" step="0.1" min="0" :disabled="store.feeConfirmed">
                  <span class="ocean-total-unit">元</span>
                </span>
              </div>
            </div>
          </div>

          <!-- 其他费用 section -->
          <div class="fee-section ocean ocean-body" :class="{ open: sections.other }" data-fee-group="other">
            <div class="fee-section-header" @click="toggleSection('other')">
              <div class="fee-section-icon"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="10"/><line x1="12" y1="8" x2="12" y2="16"/><line x1="8" y1="12" x2="16" y2="12"/></svg></div>
              <div class="fee-section-title">其他费用</div>
              <div class="fee-section-summary">¥{{ formatFee(otherTotal) }}</div>
              <svg class="fee-section-arrow" viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><polyline points="6 4 10 8 6 12"/></svg>
            </div>
            <div class="fee-section-body ocean-body" id="fpOtherFeeBody">
              <div class="other-fee-row" v-for="(o, idx) in store.feeData.other" :key="idx">
                <input type="text" class="other-fee-name" placeholder="费用类型" v-model="o.name" :disabled="store.feeConfirmed">
                <input type="number" class="other-fee-amount" placeholder="金额" step="0.1" min="0" v-model.number="o.amount" :disabled="store.feeConfirmed">
                <button class="other-fee-remove" v-if="!store.feeConfirmed" @click="removeOther(idx)">
                  <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/></svg>
                </button>
              </div>
              <div class="other-fee-add" v-if="!store.feeConfirmed" @click="addOtherRow">
                <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><line x1="12" y1="5" x2="12" y2="19"/><line x1="5" y1="12" x2="19" y2="12"/></svg>
                添加其他费用
              </div>
            </div>
          </div>

          <!-- 总计 -->
          <div class="fee-total-row">
            <div class="fee-total-label">费用总计</div>
            <div>
              <span class="fee-total-value" id="fpGrandTotal">¥{{ formatFee(totalFees) }}</span>
              <span class="fee-total-unit">元</span>
            </div>
          </div>

          <!-- 操作按钮：重新优化 + 费用信息确认 -->
          <div class="fee-actions">
            <button type="button" class="confirm-fee-btn" v-if="!store.feeConfirmed" @click="confirmFees">
              <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" style="width:16px;height:16px;vertical-align:middle;margin-right:4px"><path d="M22 11.08V12a10 10 0 1 1-5.93-9.14"/><polyline points="22 4 12 14.01 9 11.01"/></svg>
              费用信息确认
            </button>
            <button type="button" class="edit-fee-btn" v-if="store.feeConfirmed" @click="unlockFees">
              <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" style="width:16px;height:16px;vertical-align:middle;margin-right:4px"><path d="M1 4v6h6"/><path d="M3.51 15a9 9 0 1 0 2.13-9.36L1 10"/></svg>
              返回修改
            </button>
          </div>
        </div>
    `,
};
