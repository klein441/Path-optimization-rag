/**
 * 费用信息确认弹窗（表单页）
 */
import { reactive } from '../../vendor/vue.esm-browser.prod.js';
import { store } from '../state.js';
import { TRANSPORT_MODE_FREIGHT } from '../constants.js';
import { formatFee, showNotification, autoEnableICS2ForEurope } from '../utils.js';
import { initLandFees, calculateTollFee, getSeaManagerTotal, getOtherTotal, calculateAllFees } from '../fees.js';
import { fetchOceanFreightRate } from '../ocean.js';
import OceanQuotes from './OceanQuotes.js';

export default {
    components: { OceanQuotes },
    data() {
        return {
            store: store,
            sections: reactive({ land: true, seaManager: false, portMisc: false, ocean: false, other: false }),
        };
    },
    watch: {
        'store.modalOpen'(val) {
            if (val) {
                autoEnableICS2ForEurope();
                fetchOceanFreightRate();
            }
        },
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
    },
    methods: {
        formatFee: formatFee,
        toggleSection(name) {
            const wasOpen = this.sections[name];
            this.sections[name] = !this.sections[name];
            if (!wasOpen && name === 'ocean') {
                if (this.store.form.destCountry && !this.store.ocean.realtime) {
                    fetchOceanFreightRate();
                }
            }
        },
        close() {
            this.store.modalOpen = false;
        },
        onTransportModeChange() {
            const l = this.store.feeData.land;
            initLandFees(l.factoryProvince, l.transportMode, l.factoryName, l.originPort);
            if (l.transportMode === 'factorySelf') {
                calculateTollFee();
            }
        },
        onManifestModeChange() {
            const sm = this.store.feeData.seaManager;
            if (sm.manifestMode !== 'custom') {
                sm.manifestFee = parseFloat(sm.manifestMode) || 0;
            }
        },
        onIcs2Toggle() {
            if (!this.store.feeData.seaManager.ics2Enabled) {
                this.store.feeData.seaManager.ics2Fee = 0;
            }
        },
        addOtherRow() {
            this.store.feeData.other.push({ name: '', amount: 0 });
        },
        removeOther(idx) {
            this.store.feeData.other.splice(idx, 1);
        },
        refresh() {
            fetchOceanFreightRate();
        },
        confirm() {
            calculateAllFees();
            this.store.modalOpen = false;
            this.store.metaText = '推荐方案';
            showNotification('费用信息已确认！点击"智能路径推荐"获取方案。');
        },
    },
    template: `
        <div class="modal-overlay" id="costInfoModal" :class="{ open: store.modalOpen }" @click.self="close">
          <div class="modal">
            <div class="modal-header">
              <h2>
                <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><rect x="1" y="4" width="22" height="16" rx="2"/><line x1="1" y1="10" x2="23" y2="10"/><line x1="10" y1="4" x2="10" y2="20"/></svg>
                费用信息确认
              </h2>
              <button class="modal-close" id="costInfoClose" title="关闭" @click="close">
                <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/></svg>
              </button>
            </div>
            <div class="modal-body" id="costInfoBody">

              <!-- 推荐航线信息 -->
              <div class="route-info-card" id="routeInfoCard">
                <div class="route-info-item">
                  <div class="route-info-item-label">发货工厂</div>
                  <div class="route-info-item-value" id="routeInfoFactory">{{ store.routeInfoCard.factory }}</div>
                </div>
                <div class="route-info-arrow">→</div>
                <div class="route-info-item">
                  <div class="route-info-item-label">始发港</div>
                  <div class="route-info-item-value" id="routeInfoOrigin">{{ store.routeInfoCard.origin }}</div>
                </div>
                <div class="route-info-arrow">→</div>
                <div class="route-info-item">
                  <div class="route-info-item-label">终到港</div>
                  <div class="route-info-item-value" id="routeInfoDest">{{ store.routeInfoCard.dest }}</div>
                </div>
              </div>

              <!-- 出口起运港拖车费 -->
              <div class="fee-section" :class="{ open: sections.land }" data-fee-group="land">
                <div class="fee-section-header" @click="toggleSection('land')">
                  <div class="fee-section-icon">
                    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><rect x="1" y="3" width="15" height="13"/><polygon points="16 8 20 8 23 11 23 16 16 16 16 8"/><circle cx="5.5" cy="18.5" r="2.5"/><circle cx="18.5" cy="18.5" r="2.5"/></svg>
                  </div>
                  <div class="fee-section-title">出口起运港拖车费</div>
                  <div class="fee-section-summary" id="landFeeSummary">¥{{ formatFee(landTotal) }}</div>
                  <svg class="fee-section-arrow" viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><polyline points="6 4 10 8 6 12"/></svg>
                </div>
                <div class="fee-section-body">
                  <div class="fee-item">
                    <div class="fee-item-label">运输方式</div>
                    <select class="fee-select" id="transportModeSelect" v-model="store.feeData.land.transportMode" @change="onTransportModeChange">
                      <option value="direct">直拖</option>
                      <option value="seaRail">海铁</option>
                      <option value="factorySelf">工厂自运</option>
                      <option value="landToWater">陆改水</option>
                    </select>
                  </div>
                  <div class="fee-item">
                    <div class="fee-item-label">陆运费</div>
                    <input type="number" class="fee-item-input" id="landBaseFreight" v-model.number="store.feeData.land.baseFreight" step="0.1" min="0">
                    <span class="fee-item-unit">元</span>
                  </div>
                  <div class="fee-item" id="tollFeeItem" v-show="modeConf.hasToll">
                    <div class="fee-item-label">高速费</div>
                    <div class="toggle-wrap">
                      <label class="toggle-switch">
                        <input type="checkbox" id="landTollToggle" v-model="store.feeData.land.tollEnabled">
                        <span class="toggle-slider"></span>
                      </label>
                      <span class="toggle-label">产生</span>
                    </div>
                    <input type="number" class="fee-item-input small" id="landTollFee" placeholder="高速费" v-model.number="store.feeData.land.tollFee" step="0.1" min="0">
                    <span class="fee-item-unit">元</span>
                  </div>
                  <div class="fee-item" id="insideLoadItem" v-show="insideVisible">
                    <div class="fee-item-label">内装费 <span class="info-badge" id="insideLoadBadge">江西/安庆基地</span></div>
                    <div class="toggle-wrap">
                      <label class="toggle-switch">
                        <input type="checkbox" id="insideLoadToggle" v-model="store.feeData.land.insideLoadEnabled">
                        <span class="toggle-slider"></span>
                      </label>
                      <span class="toggle-label">需要</span>
                    </div>
                    <input type="number" class="fee-item-input small" id="insideLoadFee" placeholder="内装费" v-model.number="store.feeData.land.insideLoadFee" step="0.1" min="0">
                    <span class="fee-item-unit">元</span>
                  </div>
                </div>
              </div>

              <!-- 海管家费用 -->
              <div class="fee-section" :class="{ open: sections.seaManager }" data-fee-group="seaManager">
                <div class="fee-section-header" @click="toggleSection('seaManager')">
                  <div class="fee-section-icon">
                    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M3 18s1.5-2 4.5-2 4.5 2 9 2 4.5-2 4.5-2"/><path d="M21 12l-9-7-9 7"/><path d="M12 2l0 18"/></svg>
                  </div>
                  <div class="fee-section-title">海管家费用</div>
                  <div class="fee-section-summary" id="seaManagerFeeSummary">¥{{ formatFee(seaManagerTotal) }}</div>
                  <svg class="fee-section-arrow" viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><polyline points="6 4 10 8 6 12"/></svg>
                </div>
                <div class="fee-section-body">
                  <div class="fee-item">
                    <div class="fee-item-label">舱单费</div>
                    <select class="fee-select" id="manifestFeeSelect" v-model="store.feeData.seaManager.manifestMode" @change="onManifestModeChange">
                      <option value="55">默认 55</option>
                      <option value="25">25</option>
                      <option value="35">35</option>
                      <option value="80">80</option>
                      <option value="custom">自定义</option>
                    </select>
                    <input type="number" class="fee-item-input small" id="manifestFeeCustom" placeholder="自定义" step="0.1" min="0" v-if="store.feeData.seaManager.manifestMode === 'custom'" v-model.number="store.feeData.seaManager.manifestFee">
                    <span class="fee-item-unit">元</span>
                  </div>
                  <div class="fee-item">
                    <div class="fee-item-label">VGM费</div>
                    <input type="number" class="fee-item-input" id="vgmFee" v-model.number="store.feeData.seaManager.vgmFee" step="0.1" min="0">
                    <span class="fee-item-unit">元</span>
                  </div>
                  <div class="fee-item">
                    <div class="fee-item-label">ICS2费 <span class="info-badge">仅欧洲</span></div>
                    <div class="toggle-wrap">
                      <label class="toggle-switch">
                        <input type="checkbox" id="ics2Toggle" v-model="store.feeData.seaManager.ics2Enabled" @change="onIcs2Toggle">
                        <span class="toggle-slider"></span>
                      </label>
                      <span class="toggle-label">启用</span>
                    </div>
                    <input type="number" class="fee-item-input small" id="ics2Fee" placeholder="ICS2费" step="0.1" min="0" v-if="store.feeData.seaManager.ics2Enabled" v-model.number="store.feeData.seaManager.ics2Fee">
                    <span class="fee-item-unit" v-if="store.feeData.seaManager.ics2Enabled">元</span>
                  </div>
                </div>
              </div>

              <!-- 港杂费 -->
              <div class="fee-section" :class="{ open: sections.portMisc }" data-fee-group="portMisc">
                <div class="fee-section-header" @click="toggleSection('portMisc')">
                  <div class="fee-section-icon">
                    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M2 12h20"/><path d="M12 2a15.3 15.3 0 0 1 4 10 15.3 15.3 0 0 1-4 10 15.3 15.3 0 0 1-4-10 15.3 15.3 0 0 1 4-10z"/><circle cx="12" cy="12" r="3"/></svg>
                  </div>
                  <div class="fee-section-title">港杂费</div>
                  <div class="fee-section-summary" id="portMiscFeeSummary">¥{{ formatFee(store.feeData.portMisc.fee) }}</div>
                  <svg class="fee-section-arrow" viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><polyline points="6 4 10 8 6 12"/></svg>
                </div>
                <div class="fee-section-body">
                  <div class="fee-item">
                    <div class="fee-item-label">港杂费合计</div>
                    <input type="number" class="fee-item-input" id="portMiscFee" v-model.number="store.feeData.portMisc.fee" step="0.1" min="0">
                    <span class="fee-item-unit">元</span>
                  </div>
                </div>
              </div>

              <!-- 海运费 -->
              <div class="fee-section" :class="{ open: sections.ocean }" data-fee-group="ocean">
                <div class="fee-section-header" @click="toggleSection('ocean')">
                  <div class="fee-section-icon">
                    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M3 18s1.5-2 4.5-2 4.5 2 9 2 4.5-2 4.5-2"/><path d="M21 12l-9-7-9 7"/><path d="M12 2l0 18"/></svg>
                  </div>
                  <div class="fee-section-title">海运费</div>
                  <div class="fee-section-summary" id="oceanFeeSummary">¥{{ formatFee(store.feeData.ocean.fee) }}</div>
                  <svg class="fee-section-arrow" viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><polyline points="6 4 10 8 6 12"/></svg>
                </div>
                <div class="fee-section-body">
                  <!-- 合约报价成功展示 -->
                  <div class="ocean-realtime" id="oceanRealtime" v-show="store.ocean.realtime">
                    <div class="ocean-realtime-header">
                      <div class="ocean-realtime-source">
                        <span class="live-dot" style="background:#10b981;box-shadow:0 0 8px #10b981"></span>
                        <span>合约报价 · 合约信息导出0806.xlsx</span>
                      </div>
                      <div class="ocean-realtime-actions">
                        <button class="ocean-refresh" id="oceanRefreshBtn" @click="refresh" title="重新加载合约报价">
                          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><polyline points="23 4 23 10 17 10"/><polyline points="1 20 1 14 7 14"/><path d="M3.51 9a9 9 0 0 1 14.85-3.36L23 10M1 14l4.64 4.36A9 9 0 0 0 20.49 15"/></svg>
                          <span>刷新</span>
                        </button>
                      </div>
                    </div>
                    <div class="ocean-realtime-rates">
                      <div class="ocean-rate-item primary" style="flex:1">
                        <div class="ocean-rate-value" id="oceanMedianRate">{{ store.ocean.medianRateText }}</div>
                      </div>
                    </div>
                    <div class="ocean-realtime-meta">
                      <span id="oceanRouteInfo">{{ store.ocean.routeInfoText }}</span><span class="dot">·</span>
                      <span id="oceanTransitInfo">{{ store.ocean.transitInfoText }}</span><span class="dot">·</span>
                      <span id="oceanFetchedAt">{{ store.ocean.fetchedAtText }}</span>
                    </div>
                    <div class="ocean-realtime-tags">
                      <span class="ocean-tag factory-tag" id="oceanFactoryTag">{{ store.ocean.factoryTagText }}</span>
                      <span class="ocean-tag fcl-tag" id="oceanFCLTag">普货 · FCL整箱</span>
                      <span class="ocean-tag carrier-tag" id="oceanShippingLine">{{ store.ocean.shippingLineText }}</span>
                    </div>
                    <div class="ocean-realtime-quotes" id="oceanQuotesList" v-show="store.ocean.carriers.length">
                      <div style="font-weight:600;font-size:13px;color:#334155;margin-bottom:10px;display:flex;align-items:center;gap:6px">
                        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" style="width:14px;height:14px;color:var(--accent)"><rect x="3" y="3" width="18" height="18" rx="2" ry="2"/><line x1="3" y1="9" x2="21" y2="9"/><line x1="9" y1="21" x2="9" y2="9"/></svg>
                        各船公司合约报价
                      </div>
                      <div id="oceanQuotesGrid" style="overflow-x:auto"><OceanQuotes /></div>
                    </div>
                  </div>

                  <!-- 加载中 -->
                  <div class="ocean-loading" id="oceanLoading" v-show="store.ocean.loading">
                    <div class="ocean-spinner"></div>
                    <span>正在从合约表加载海运费报价...</span>
                  </div>

                  <!-- 加载失败 -->
                  <div class="ocean-error" id="oceanError" v-show="store.ocean.error">
                    <div class="ocean-error-icon">
                      <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="10"/><line x1="15" y1="9" x2="9" y2="15"/><line x1="9" y1="9" x2="15" y2="15"/></svg>
                    </div>
                    <div>
                      <div class="ocean-error-title">合约报价未匹配</div>
                      <div class="ocean-error-desc" id="oceanErrorDesc">{{ store.ocean.errorDesc }}</div>
                    </div>
                    <button class="ocean-retry" id="oceanRetryBtn" @click="refresh">重试</button>
                  </div>

                  <div class="fee-item">
                    <div class="fee-item-label">海运费合计</div>
                    <input type="number" class="fee-item-input" id="oceanFee" v-model.number="store.feeData.ocean.fee" step="0.1" min="0">
                    <span class="fee-item-unit">元</span>
                  </div>
                </div>
              </div>

              <!-- 其他费用 -->
              <div class="fee-section" :class="{ open: sections.other }" data-fee-group="other">
                <div class="fee-section-header" @click="toggleSection('other')">
                  <div class="fee-section-icon">
                    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="10"/><line x1="12" y1="8" x2="12" y2="16"/><line x1="8" y1="12" x2="16" y2="12"/></svg>
                  </div>
                  <div class="fee-section-title">其他费用</div>
                  <div class="fee-section-summary" id="otherFeeSummary">¥{{ formatFee(otherTotal) }}</div>
                  <svg class="fee-section-arrow" viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><polyline points="6 4 10 8 6 12"/></svg>
                </div>
                <div class="fee-section-body" id="otherFeeBody">
                  <div class="other-fee-row" v-for="(o, idx) in store.feeData.other" :key="idx">
                    <input type="text" class="other-fee-name" placeholder="费用类型（如：熏蒸费、报关费等）" v-model="o.name">
                    <input type="number" class="other-fee-amount" placeholder="金额" step="0.1" min="0" v-model.number="o.amount">
                    <button class="other-fee-remove" title="删除" @click="removeOther(idx)">
                      <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/></svg>
                    </button>
                  </div>
                  <div class="other-fee-add" @click="addOtherRow">
                    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><line x1="12" y1="5" x2="12" y2="19"/><line x1="5" y1="12" x2="19" y2="12"/></svg>
                    添加其他费用
                  </div>
                </div>
              </div>

              <!-- 费用合计 -->
              <div class="fee-total-row">
                <div class="fee-total-label">费用总计</div>
                <div>
                  <span class="fee-total-value" id="grandTotal">¥{{ formatFee(totalFees) }}</span>
                  <span class="fee-total-unit">元</span>
                </div>
              </div>

            </div>
            <div class="modal-footer">
              <button class="btn-primary" id="costInfoConfirm" style="margin-top:0;max-width:200px" @click="confirm">
                <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><polyline points="20 6 9 17 4 12"/></svg>
                <span>确认费用</span>
              </button>
            </div>
          </div>
        </div>
    `,
};