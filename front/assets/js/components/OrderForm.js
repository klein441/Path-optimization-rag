/**
 * 运输需求录入表单
 */
import { store } from '../state.js';
import { BOX_VOLUMES, PRODUCT_OPTIONS, BOX_TYPE_OPTIONS, GLOVE_WEIGHT_KG_PER_THOUSAND, GLOVE_UNIT_TO_THOUSAND } from '../constants.js';
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
            sizeMsOpenFor: '',
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
        gloveQtyTotal() {
            let total = 0;
            Object.entries(store.form.gloveQuantities || {}).forEach(([p, sizes]) => {
                if (!store.form.productTypes.includes(p)) return;
                const selectedSizes = store.form.productSizes[p] || [];
                Object.entries(sizes || {}).forEach(([s, v]) => {
                    if (selectedSizes.includes(s)) {
                        total += parseFloat(v) || 0;
                    }
                });
            });
            return Math.round(total);
        },
        gloveWeightTotal() {
            let total = 0;
            const unitFactor = GLOVE_UNIT_TO_THOUSAND[this.store.form.gloveUnit] || 1;
            Object.entries(this.store.form.gloveQuantities || {}).forEach(([p, sizes]) => {
                if (!this.store.form.productTypes.includes(p)) return;
                const selectedSizes = this.store.form.productSizes[p] || [];
                const typeWeights = GLOVE_WEIGHT_KG_PER_THOUSAND[p] || {};
                Object.entries(sizes || {}).forEach(([s, v]) => {
                    if (!selectedSizes.includes(s)) return;
                    const qty = parseFloat(v) || 0;
                    if (qty <= 0) return;
                    const kgPerThousand = typeWeights[s] || typeWeights.M || 0;
                    total += qty * unitFactor * kgPerThousand;
                });
            });
            return Math.round(total);
        },
    },
    watch: {
        boxWatchKey() { this.syncBoxDerived(); },
        'store.form.gloveUnit'() { this.syncGloveQty(); },
        productWatchKey(joined) {
            const arr = joined ? joined.split(',') : [];
            const newSizes = {};
            const newQuantities = {};
            arr.forEach(p => {
                const sizes = this.store.form.productSizes[p];
                const selectedSizes = Array.isArray(sizes) ? sizes.slice() : [];
                newSizes[p] = selectedSizes;
                const oldQty = store.form.gloveQuantities[p] || {};
                const qty = {};
                selectedSizes.forEach(s => {
                    qty[s] = parseFloat(oldQty[s]) || 0;
                });
                newQuantities[p] = qty;
            });
            this.store.form.productSizes = newSizes;
            this.store.form.gloveQuantities = newQuantities;
            this.syncGloveQty();
        },
    },
    mounted() {
        initDateDefaults();
        this.loadCountries();
        document.addEventListener('click', this.closeMs);
        this.syncBoxDerived();
        this.syncGloveQty();
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
            this.sizeMsOpenFor = '';
        },
        toggleSizeMs(p) {
            this.sizeMsOpenFor = this.sizeMsOpenFor === p ? '' : p;
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
        // ===== 尺码选择（多选） =====
        onSizeToggle(p, size, e) {
            const arr = Array.isArray(store.form.productSizes[p]) ? store.form.productSizes[p].slice() : [];
            const idx = arr.indexOf(size);
            if (e.target.checked) {
                if (idx < 0) arr.push(size);
            } else if (idx >= 0) {
                arr.splice(idx, 1);
            }
            store.form.productSizes[p] = arr;
            const qty = Object.assign({}, store.form.gloveQuantities[p] || {});
            if (e.target.checked && !(size in qty)) qty[size] = 0;
            store.form.gloveQuantities[p] = qty;
            this.syncGloveQty();
        },
        onGloveQtyInput(p, size, e) {
            const qty = Object.assign({}, store.form.gloveQuantities[p] || {});
            qty[size] = Math.max(0, parseInt(e.target.value) || 0);
            store.form.gloveQuantities[p] = qty;
            this.syncGloveQty();
        },
        syncGloveQty() {
            store.form.gloveQty = this.gloveQtyTotal || 0;
            this.syncWeight();
        },
        // ===== 柜型数量 =====
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
                store.form.volumeHint = '请先选择集装箱柜型';
                this.syncWeight();
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
            store.form.weight = this.gloveWeightTotal;
        },
        boxTypeLabel(bt) {
            const opt = BOX_TYPE_OPTIONS.find(o => o.value === bt);
            return opt ? opt.label : bt;
        },
        onSubmit() {
            handleSubmit();
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
              <div class="multi-select product-type-selector" id="productTypeMulti" :class="{ open: store.productMsOpen }">
                <div class="multi-select-trigger" @click.stop="toggleMs('product')">
                  <span class="multi-select-placeholder" v-if="store.form.productTypes.length === 0">请选择产品类型（支持多选）</span>
                  <span class="product-type-summary" v-else>已选 {{ store.form.productTypes.length }} 种产品</span>
                  <svg class="ms-arrow" viewBox="0 0 12 12" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><polyline points="3 5 6 8 9 5"/></svg>
                </div>
                <div class="multi-select-dropdown" v-show="store.productMsOpen">
                  <label class="ms-option" :class="{ selected: store.form.productTypes.includes(opt.value) }" v-for="opt in PRODUCT_OPTIONS" :key="opt.value">
                    <input type="checkbox" :value="opt.value" :checked="store.form.productTypes.includes(opt.value)" @change="onProductToggle(opt.value, $event)"><span>{{ opt.label }}</span>
                  </label>
                </div>
              </div>
              <div id="productSizeContainer" class="product-size-container" v-show="store.form.productTypes.length">
                <div class="product-size-row" v-for="p in store.form.productTypes" :key="p">
                  <span class="product-size-label">{{ p }}<span class="ms-tag-x" @click.stop="removeProduct(p)">×</span></span>
                  <div class="multi-select product-size-selector" :class="{ open: sizeMsOpenFor === p }">
                    <div class="multi-select-trigger" @click.stop="toggleSizeMs(p)">
                      <span class="multi-select-placeholder" v-if="(store.form.productSizes[p] || []).length === 0">选择尺码</span>
                      <span class="multi-select-tags" v-else>
                        <span class="ms-tag" v-for="s in store.form.productSizes[p]" :key="s">{{ s }}</span>
                      </span>
                      <svg class="ms-arrow" viewBox="0 0 12 12" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><polyline points="3 5 6 8 9 5"/></svg>
                    </div>
                    <div class="multi-select-dropdown" v-show="sizeMsOpenFor === p" @click.stop>
                      <label class="ms-option" :class="{ selected: (store.form.productSizes[p] || []).includes(s) }" v-for="s in ['S','M','L','XL']" :key="s">
                        <input type="checkbox" :checked="(store.form.productSizes[p] || []).includes(s)" @change="onSizeToggle(p, s, $event)">
                        <span>{{ s }}</span>
                      </label>
                    </div>
                  </div>
                </div>
              </div>
            </div>

            <div class="form-group full">
              <label class="form-label">手套数量 <span class="req">*</span></label>
              <div class="glove-qty-toggle" :class="{ open: store.gloveQtyPanelOpen }" @click="store.gloveQtyPanelOpen = !store.gloveQtyPanelOpen">
                <span class="glove-qty-total">合计 {{ store.form.gloveQty || 0 }} {{ store.form.gloveUnit }}</span>
                <select class="form-select glove-unit-select" v-model="store.form.gloveUnit" @click.stop>
                  <option value="千支">千支</option>
                  <option value="八百支">八百支</option>
                </select>
                <svg class="glove-qty-arrow" viewBox="0 0 12 12" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><polyline points="3 5 6 8 9 5"/></svg>
              </div>
              <div class="glove-qty-panel" :class="{ open: store.gloveQtyPanelOpen }">
                <div class="glove-qty-empty" v-if="store.form.productTypes.length === 0">请先选择产品类型</div>
                <div class="glove-qty-table" v-else>
                  <div class="glove-qty-table-head">
                    <span>手套 / 尺码</span>
                    <span>数量</span>
                  </div>
                  <template v-for="p in store.form.productTypes" :key="p">
                    <template v-for="s in ['S','M','L','XL']" :key="p + '-' + s">
                      <div class="glove-qty-table-row" v-if="(store.form.productSizes[p] || []).includes(s)">
                        <span class="glove-qty-product">{{ s }}码{{ p }}</span>
                        <input type="number" class="glove-qty-input" :disabled="!(store.form.productSizes[p] || []).includes(s)" :value="((store.form.gloveQuantities[p] || {})[s] || 0)" min="0" step="1" @input="onGloveQtyInput(p, s, $event)">
                      </div>
                    </template>
                  </template>
                </div>
              </div>
            </div>

            <div class="form-group full">
              <label class="form-label">集装箱柜型 <span class="req">*</span></label>
              <div class="multi-select" id="boxTypeMulti" :class="{ open: store.boxMsOpen }">
                <div class="multi-select-trigger" @click.stop="toggleMs('box')">
                  <span class="multi-select-placeholder" v-if="store.form.boxTypes.length === 0">请选择集装箱柜型（支持多选）</span>
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

            <!-- 每种柜型数量输入（动态生成） -->
            <div class="form-group full" id="boxTypeQuantitiesGroup" v-show="store.form.boxTypes.length">
              <label class="form-label">各柜型数量</label>
              <div id="boxTypeQuantities">
                <div class="box-qty-row" v-for="bt in store.form.boxTypes" :key="bt">
                  <span class="box-qty-type">{{ bt }}</span>
                  <span class="box-qty-volume">{{ BOX_VOLUMES[bt] }} m³/柜</span>
                  <span class="box-qty-label">数量:</span>
                  <input type="number" class="box-qty-input" :value="store.form.boxTypeCounts[bt] || 1" min="1" max="9999" step="1" @input="onBoxQtyInput(bt, $event)">
                </div>
                <div class="box-qty-summary">
                  装柜总数: <span>{{ store.form.boxes }} 柜</span>
                  总体积合计: <span>{{ store.form.volume.toFixed(1) }} m³</span>
                </div>
              </div>
            </div>

            <div class="form-group">
              <label class="form-label">装柜总数</label>
              <div class="input-prefix">
                <input type="number" class="form-input" id="boxes" min="1" readonly style="padding-right:2.5rem;background:var(--rule-weak);color:var(--muted)" :value="store.form.boxes">
                <span class="unit">柜</span>
              </div>
            </div>

            <div class="form-group">
              <label class="form-label">总重量</label>
              <div class="input-prefix">
                <input type="number" class="form-input" id="weight" min="0" readonly style="padding-right:2.5rem;background:var(--rule-weak);color:var(--muted)" :value="store.form.weight">
                <span class="unit">kg</span>
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
              <label class="form-label">客户要求到货时间</label>
              <input type="date" class="form-input" id="requiredArrival" v-model="store.form.requiredArrival">
            </div>

            <div class="form-group full">
              <label class="form-label">贸易条款偏好</label>
              <select class="form-select" id="tradePref" v-model="store.form.tradePref">
                <option value="FOB">FOB (F条款)</option>
                <option value="FCA">FCA (F条款)</option>
                <option value="FAS">FAS (F条款)</option>
                <option value="CIF">CIF (C条款)</option>
                <option value="DDP">DDP (D条款)</option>
              </select>
            </div>
            <div class="form-group full">
              <label class="form-label" style="display:flex;align-items:center;gap:0.4rem;text-transform:none;letter-spacing:0">
                <input type="checkbox" v-model="store.form.urgent" style="accent-color:var(--accent);width:15px;height:15px">
                加急（优先保证到货时效）
              </label>
            </div>
            <div class="form-group full">
              <label class="form-label">备注 / 特殊要求</label>
              <textarea class="form-textarea" id="remarks" placeholder="如：需FDA认证、温度控制、加急等" v-model="store.form.remarks"></textarea>
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
