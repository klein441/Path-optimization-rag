/**
 * 运输需求录入表单
 */
import { store } from '../state.js';
import { BOX_VOLUMES, PRODUCT_OPTIONS, BOX_TYPE_OPTIONS } from '../constants.js';
import { initDateDefaults } from '../utils.js';
import { apiGetCountries, apiGetDestPorts } from '../api.js';
import { handleSubmit } from '../submit.js';

export default {
    data() {
        return {
            store: store,
            PRODUCT_OPTIONS: PRODUCT_OPTIONS,
            BOX_TYPE_OPTIONS: BOX_TYPE_OPTIONS,
            BOX_VOLUMES: BOX_VOLUMES,
        };
    },
    computed: {
        boxWatchKey() {
            return this.store.form.boxTypes.join(',') + '|' + JSON.stringify(this.store.form.boxTypeCounts);
        },
        productWatchKey() {
            return this.store.form.productTypes.join(',');
        },
        totalBoxes() {
            return Object.values(this.store.form.boxTypeCounts).reduce((s, n) => s + n, 0) || 1;
        },
    },
    watch: {
        boxWatchKey() { this.syncBoxDerived(); },
        'store.form.weightPerBox'() { this.syncWeight(); },
        productWatchKey(joined) {
            const arr = joined ? joined.split(',') : [];
            const newSizes = {};
            arr.forEach(p => { newSizes[p] = this.store.form.productSizes[p] || 'M'; });
            this.store.form.productSizes = newSizes;
        },
    },
    mounted() {
        initDateDefaults();
        this.loadCountries();
        document.addEventListener('click', this.closeMs);
        this.syncBoxDerived();
    },
    beforeUnmount() {
        document.removeEventListener('click', this.closeMs);
    },
    methods: {
        async loadCountries() {
            try {
                const countries = await apiGetCountries();
                store.countries = countries;
            } catch (e) {
                console.error('[API] 加载运抵国失败:', e.message);
            } finally {
                store.countriesLoading = false;
            }
        },
        async onCountryChange() {
            store.form.destPort = '';
            const country = store.form.destCountry;
            if (!country) {
                store.destPorts = [];
                return;
            }
            store.destPortsLoading = true;
            try {
                const ports = await apiGetDestPorts(country);
                store.destPorts = ports;
            } catch (e) {
                console.warn('[API] 加载目的港失败:', e.message);
                store.destPorts = [];
            } finally {
                store.destPortsLoading = false;
            }
        },
        portDisplay(p) {
            let name = p.port;
            let display = name;
            const m = name.match(/^[A-Z]{2}[A-Z0-9]{3}\s*\/\s*(.+)/);
            if (m) display = m[1];
            return display.replace(/,\s*[A-Z]{2}$/, '').trim();
        },
        // ===== 多选组件 =====
        toggleMs(name) {
            if (name === 'product') {
                store.boxMsOpen = false;
                store.productMsOpen = !store.productMsOpen;
            } else {
                store.productMsOpen = false;
                store.boxMsOpen = !store.boxMsOpen;
            }
        },
        closeMs() {
            store.productMsOpen = false;
            store.boxMsOpen = false;
        },
        onProductToggle(value, e) {
            const arr = store.form.productTypes.slice();
            const i = arr.indexOf(value);
            if (e.target.checked) { if (i < 0) arr.push(value); }
            else { if (i >= 0) arr.splice(i, 1); }
            store.form.productTypes = arr;
        },
        onBoxTypeToggle(value, e) {
            const arr = store.form.boxTypes.slice();
            const i = arr.indexOf(value);
            if (e.target.checked) { if (i < 0) arr.push(value); }
            else { if (i >= 0) arr.splice(i, 1); }
            store.form.boxTypes = arr;
        },
        removeProduct(p) {
            const i = store.form.productTypes.indexOf(p);
            if (i >= 0) store.form.productTypes.splice(i, 1);
        },
        removeBoxType(bt) {
            const i = store.form.boxTypes.indexOf(bt);
            if (i >= 0) store.form.boxTypes.splice(i, 1);
        },
        // ===== 尺码选择 =====
        onSizeChange(p, e) {
            store.form.productSizes[p] = e.target.value;
        },
        // ===== 箱型数量 =====
        onBoxQtyInput(bt, e) {
            const n = parseInt(e.target.value) || 1;
            store.form.boxTypeCounts[bt] = Math.max(1, n);
        },
        syncBoxDerived() {
            const selected = store.form.boxTypes;
            const newCounts = {};
            selected.forEach(bt => { newCounts[bt] = store.form.boxTypeCounts[bt] || 1; });
            store.form.boxTypeCounts = newCounts;
            if (selected.length === 0) {
                store.form.boxes = 1;
                store.form.volume = 0;
                store.form.volumeHint = '请先选择集装箱箱型';
                store.form.weight = 15;
                return;
            }
            const totalBoxes = Object.values(newCounts).reduce((s, n) => s + n, 0);
            const totalVolume = selected.reduce((sum, bt) => sum + (BOX_VOLUMES[bt] || 0) * (newCounts[bt] || 1), 0);
            store.form.boxes = totalBoxes;
            store.form.volume = Math.round(totalVolume * 10) / 10;
            store.form.volumeHint = selected.map(bt => `${newCounts[bt] || 1}×${bt}(${BOX_VOLUMES[bt]}m³)`).join(' + ') + ` = ${totalVolume.toFixed(1)} m³`;
            this.syncWeight();
        },
        syncWeight() {
            const totalBoxes = parseInt(store.form.boxes) || 1;
            const wpb = parseFloat(store.form.weightPerBox) || 15;
            store.form.weight = Math.round(wpb * totalBoxes);
        },
        boxSubtotal(bt) {
            return ((BOX_VOLUMES[bt] || 0) * (store.form.boxTypeCounts[bt] || 1)).toFixed(1);
        },
        boxTypeLabel(bt) {
            const opt = BOX_TYPE_OPTIONS.find(o => o.value === bt);
            return opt ? opt.label : bt;
        },
        onSubmit() {
            handleSubmit();
        },
        openCostModal() {
            store.modalOpen = true;
        },
        toggleAdvanced() {
            store.advancedOpen = !store.advancedOpen;
        },
    },
    template: `
    <section class="panel input-panel">
      <div class="panel-header">
        <div class="icon-wrap">
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M9 11H3a1 1 0 0 0-1 1v9a1 1 0 0 0 1 1h6"/><path d="M21 11h-6a1 1 0 0 0-1 1v9a1 1 0 0 0 1 1h6"/><rect x="9" y="3" width="6" height="18" rx="1"/></svg>
        </div>
        <h2>运输需求录入</h2>
        <button type="button" class="btn-primary" id="costInfoBtn" style="margin-left:auto;padding:0.55rem 1rem;max-width:190px" @click="openCostModal">
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><rect x="1" y="4" width="22" height="16" rx="2"/><line x1="1" y1="10" x2="23" y2="10"/><line x1="10" y1="4" x2="10" y2="20"/></svg>
          <span>费用信息确认</span>
        </button>
      </div>
      <div class="panel-body">
        <form id="logisticsForm" autocomplete="off" @submit.prevent="onSubmit">
          <div class="form-grid">

            <div class="form-group full">
              <label class="form-label">订单编号 <span class="req">*</span></label>
              <input type="text" class="form-input" id="orderNumber" placeholder="请输入订单编号，如 PO-2024-001" v-model="store.form.orderNumber">
            </div>

            <div class="form-group full">
              <label class="form-label">客户名称 <span class="req">*</span></label>
              <input type="text" class="form-input" id="customer" placeholder="请输入客户名称，如 Medline Inc." v-model="store.form.customer">
            </div>

            <div class="form-group full">
              <label class="form-label">产品类型 <span class="req">*</span></label>
              <div class="multi-select" id="productTypeMulti" :class="{ open: store.productMsOpen }">
                <div class="multi-select-trigger" @click.stop="toggleMs('product')">
                  <span class="multi-select-placeholder" v-if="store.form.productTypes.length === 0">请选择产品类型（支持多选）</span>
                  <span class="multi-select-tags" v-else>
                    <span class="ms-tag" v-for="p in store.form.productTypes" :key="p">{{ p.split('（')[0] }}<span class="ms-tag-x" @click.stop="removeProduct(p)">×</span></span>
                  </span>
                  <svg class="ms-arrow" viewBox="0 0 12 12" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><polyline points="3 5 6 8 9 5"/></svg>
                </div>
                <div class="multi-select-dropdown" v-show="store.productMsOpen">
                  <label class="ms-option" :class="{ selected: store.form.productTypes.includes(opt.value) }" v-for="opt in PRODUCT_OPTIONS" :key="opt.value">
                    <input type="checkbox" :value="opt.value" :checked="store.form.productTypes.includes(opt.value)" @change="onProductToggle(opt.value, $event)"><span>{{ opt.label }}</span>
                  </label>
                </div>
              </div>
              <div id="productSizeContainer" style="margin-top:0.6rem" v-show="store.form.productTypes.length">
                <div class="product-size-row" v-for="p in store.form.productTypes" :key="p">
                  <span class="product-size-label">{{ p }}</span>
                  <select class="product-size-select" :value="store.form.productSizes[p] || 'M'" @change="onSizeChange(p, $event)">
                    <option value="S">S</option>
                    <option value="M">M</option>
                    <option value="L">L</option>
                    <option value="XL">XL</option>
                  </select>
                </div>
              </div>
            </div>

            <div class="form-group full">
              <label class="form-label">集装箱箱型 <span class="req">*</span></label>
              <div class="multi-select" id="boxTypeMulti" :class="{ open: store.boxMsOpen }">
                <div class="multi-select-trigger" @click.stop="toggleMs('box')">
                  <span class="multi-select-placeholder" v-if="store.form.boxTypes.length === 0">请选择集装箱箱型（支持多选）</span>
                  <span class="multi-select-tags" v-else>
                    <span class="ms-tag" v-for="bt in store.form.boxTypes" :key="bt">{{ bt }}<span class="ms-tag-x" @click.stop="removeBoxType(bt)">×</span></span>
                  </span>
                  <svg class="ms-arrow" viewBox="0 0 12 12" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><polyline points="3 5 6 8 9 5"/></svg>
                </div>
                <div class="multi-select-dropdown" v-show="store.boxMsOpen">
                  <label class="ms-option" :class="{ selected: store.form.boxTypes.includes(opt.value) }" v-for="opt in BOX_TYPE_OPTIONS" :key="opt.value">
                    <input type="checkbox" :value="opt.value" :checked="store.form.boxTypes.includes(opt.value)" @change="onBoxTypeToggle(opt.value, $event)"><span>{{ opt.label }}</span>
                  </label>
                </div>
              </div>
            </div>

            <div class="form-group full">
              <label class="form-label">运抵国 / 地区 <span class="req">*</span></label>
              <select class="form-select" id="destCountry" v-model="store.form.destCountry" @change="onCountryChange">
                <option value="" v-if="store.countriesLoading">加载中...</option>
                <option value="" v-else-if="store.countries.length === 0">加载失败，请刷新</option>
                <option value="" v-else>请选择运抵国</option>
                <option v-for="c in store.countries" :key="c.name" :value="c.name">{{ c.name }}</option>
              </select>
            </div>

            <div class="form-group full">
              <label class="form-label">终到港 <span class="req">*</span></label>
              <select class="form-select" id="destPort" v-model="store.form.destPort">
                <option value="" v-if="store.destPortsLoading">加载中...</option>
                <option value="" v-else-if="!store.form.destCountry">请先选择运抵国</option>
                <option value="" v-else-if="store.destPorts.length === 0">未找到目的港，请手动输入</option>
                <option v-for="p in store.destPorts" :key="p.port" :value="p.port">{{ portDisplay(p) }}</option>
              </select>
            </div>

            <div class="form-group full">
              <label class="form-label">手套数量 <span class="req">*</span></label>
              <div class="input-prefix">
                <input type="number" class="form-input" id="gloveQty" min="1" step="1" style="padding-right:3rem" v-model.number="store.form.gloveQty">
                <span class="unit">千支</span>
              </div>
            </div>

            <!-- 每种箱型数量输入（动态生成） -->
            <div class="form-group full" id="boxTypeQuantitiesGroup" v-show="store.form.boxTypes.length">
              <label class="form-label">各箱型数量</label>
              <div id="boxTypeQuantities">
                <div class="box-qty-row" v-for="bt in store.form.boxTypes" :key="bt">
                  <span class="box-qty-type">{{ bt }}</span>
                  <span class="box-qty-volume">{{ BOX_VOLUMES[bt] }} m³/箱</span>
                  <span class="box-qty-label">数量:</span>
                  <input type="number" class="box-qty-input" :value="store.form.boxTypeCounts[bt] || 1" min="1" max="9999" step="1" @input="onBoxQtyInput(bt, $event)">
                  <span class="box-qty-subtotal">{{ boxSubtotal(bt) }} m³</span>
                </div>
                <div class="box-qty-summary">
                  装箱总数: <span>{{ store.form.boxes }} 箱</span>
                  总体积合计: <span>{{ store.form.volume.toFixed(1) }} m³</span>
                </div>
              </div>
            </div>

            <div class="form-group">
              <label class="form-label">装箱总数</label>
              <div class="input-prefix">
                <input type="number" class="form-input" id="boxes" min="1" readonly style="padding-right:2.5rem;background:var(--rule-weak);color:var(--muted)" :value="store.form.boxes">
                <span class="unit">箱</span>
              </div>
            </div>

            <div class="form-group">
              <label class="form-label">单箱平均重量</label>
              <div class="input-prefix">
                <input type="number" class="form-input" id="weightPerBox" min="0" step="0.1" style="padding-right:2.5rem" v-model.number="store.form.weightPerBox">
                <span class="unit">kg/箱</span>
              </div>
            </div>

            <div class="form-group full">
              <label class="form-label">货物总体积 <span class="req">*</span></label>
              <div class="input-prefix">
                <input type="number" class="form-input" id="volume" min="0" step="0.1" readonly style="padding-right:2.5rem;background:var(--rule-weak);color:var(--muted)" :value="store.form.volume">
                <span class="unit">m³</span>
              </div>
              <div class="form-hint" id="volumeHint">{{ store.form.volumeHint }}</div>
            </div>

            <div class="form-group">
              <label class="form-label">预计货好时间 <span class="req">*</span></label>
              <input type="date" class="form-input" id="cargoReady" v-model="store.form.cargoReady">
            </div>

            <div class="form-group">
              <label class="form-label">期望船期 <span class="req">*</span></label>
              <input type="date" class="form-input" id="shipSchedule" v-model="store.form.shipSchedule">
            </div>

            <div class="form-divider"></div>

            <div class="form-group full">
              <div class="advanced-toggle" id="advToggle" :class="{ open: store.advancedOpen }" @click="toggleAdvanced">
                <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><polyline points="9 18 15 12 9 6"/></svg>
                高级选项（贸易条款 / 运输偏好）
              </div>
              <div class="advanced-section" id="advSection" :class="{ open: store.advancedOpen }">
                <div class="form-grid" style="margin-top:0.5rem">
                  <div class="form-group">
                    <label class="form-label">贸易条款偏好</label>
                    <select class="form-select" id="tradePref" v-model="store.form.tradePref">
                      <option value="auto">智能推荐</option>
                      <option value="FOB">FOB (F条款)</option>
                      <option value="CIF">CIF (C条款)</option>
                      <option value="DDP">DDP (D条款)</option>
                    </select>
                  </div>
                  <div class="form-group">
                    <label class="form-label">运输方式偏好</label>
                    <select class="form-select" id="transportPref" v-model="store.form.transportPref">
                      <option value="auto">自动选择</option>
                      <option value="cost">成本优先</option>
                      <option value="time">时效优先</option>
                      <option value="stable">稳定性优先</option>
                    </select>
                  </div>
                  <div class="form-group full">
                    <label class="form-label">备注 / 特殊要求</label>
                    <textarea class="form-textarea" id="remarks" placeholder="如：需FDA认证、温度控制、加急等" v-model="store.form.remarks"></textarea>
                  </div>
                </div>
              </div>
            </div>

          </div>

          <button type="submit" class="btn-primary" id="submitBtn" :disabled="store.submitting">
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M12 2a10 10 0 1 0 10 10"/><path d="M22 2 12 12"/><path d="M16 2h6v6"/></svg>
            <span>{{ store.submitting ? '分析中...' : '智能路径推荐' }}</span>
          </button>
        </form>
      </div>
    </section>
    `,
};