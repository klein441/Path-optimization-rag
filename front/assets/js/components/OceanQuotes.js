/**
 * 船公司合约报价卡片网格
 * 表单页弹窗与结果页费用面板共用同一组件、同一份 store.ocean 状态，
 * 选中状态与海运费金额天然双向同步。
 */
import { store } from '../state.js';
import { selectOceanCarrier } from '../ocean.js';

export default {
    data() { return { store: store }; },
    computed: {
        selectedCarrierName() {
            const sc = this.store.feeData.ocean.selectedCarrier;
            return sc ? sc.carrier : '';
        },
        boxTypeKeys() {
            return this.store.ocean.boxTypeKeys || [];
        },
    },
    methods: {
        selectCarrier(c) {
            selectOceanCarrier(c);
        },
        rateDisplay(pd) {
            return '$' + Number(pd.rate).toLocaleString();
        },
        priceUsd(val) {
            return '$' + Number(val).toLocaleString();
        },
        subtotalUsd(pd) {
            return '$' + Number(pd.rate * pd.qty).toLocaleString();
        },
    },
    template: `
        <div class="ocean-quotes-grid">
            <div v-for="(c, idx) in store.ocean.carriers" :key="c.carrier"
                 class="ocean-quote-card"
                 :class="{ cheapest: idx === 0, expired: !c.isValid, selected: selectedCarrierName === c.carrier, disabled: store.feeConfirmed }"
                 @click="selectCarrier(c)">
                <div class="ocean-quote-card-top">
                    <div class="ocean-quote-carrier"><span v-if="idx === 0" class="star-icon">⭐</span>{{ c.carrier }}</div>
                    <div class="ocean-quote-price">{{ priceUsd(c.totalUsd) }}</div>
                </div>
                <div class="ocean-quote-card-meta">
                    <span class="valid-badge" :class="c.isValid ? 'ok' : 'expired'">{{ c.isValid ? '有效' : '过期' }}</span>
                    <span class="meta-sep">·</span>
                    <span class="meta-full">✓ 全箱型</span>
                </div>
                <div class="ocean-quote-boxes">
                    <div v-for="bt in boxTypeKeys" :key="bt" class="ocean-quote-box-line">
                        <template v-if="c.perTypeDetail[bt] && c.perTypeDetail[bt].rate !== null && c.perTypeDetail[bt].rate !== undefined">
                            <span class="box-type-label">{{ bt }}:</span>
                            <span class="box-rate">{{ rateDisplay(c.perTypeDetail[bt]) }}</span> ×
                            <span class="box-qty">{{ c.perTypeDetail[bt].qty }}</span> =
                            <span class="box-subtotal">{{ subtotalUsd(c.perTypeDetail[bt]) }}</span>
                        </template>
                    </div>
                </div>
            </div>
        </div>
    `,
};