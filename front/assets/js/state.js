/**
 * 全局响应式状态 — Vue reactive store
 */
import { reactive } from '../vendor/vue.esm-browser.prod.js';

export const store = reactive({
    // ===== 表单状态 =====
    form: {
        orderNumber: '',
        customer: 'Medline Inc.',
        productTypes: [],        // 选中的产品类型
        productSizes: {},        // { "丁腈手套": "M", "PVC手套": "L" }
        boxTypes: [],            // 选中的箱型
        boxTypeCounts: {},       // { "40HQ": 5, "20GP": 3 }
        destCountry: '',
        destPort: '',
        gloveQty: 1000,
        gloveUnit: '千支',
        weightPerBox: 15,
        cargoReady: '',
        requiredArrival: '',
        urgent: false,
        tradePref: 'FOB',
        transportPref: 'auto',
        remarks: '',
        // 派生值（由 OrderForm watcher 同步）
        boxes: 1,
        volume: 0,
        volumeHint: '请先选择集装箱箱型',
        weight: 15,
    },

    // ===== 动态下拉数据 =====
    countries: [],
    countriesLoading: true,
    destPorts: [],
    destPortsLoading: false,

    // ===== UI 开关 =====
    advancedOpen: false,
    feeConfirmed: false, // 费用信息是否已确认（结果页锁定费用输入）
    productMsOpen: false,
    boxMsOpen: false,

    // ===== 全局费用数据 =====
    feeData: {
        land: {
            transportMode: 'direct', baseFreight: 500, tollEnabled: false, tollFee: 0,
            insideLoadEnabled: false, insideLoadFee: 0, factoryProvince: '', factoryName: '', originPort: '',
            // 承运商推荐
            bestCarrier: '',        // 推荐承运商名称（最便宜）
            selectedCarrier: null,  // 用户选择的承运商对象
            carriers: [],           // 全部匹配的承运商列表
            perBoxFee: 0,           // 推荐承运商的单箱费率
            source: '',             // 数据来源
            totalMatched: 0,        // 匹配记录数
            loading: false,
            error: false,
        },
        seaManager: { manifestFee: 55, manifestCustom: 0, manifestMode: '55', vgmFee: 5, ics2Enabled: false, ics2Fee: 0 },
        portMisc: {
            fee: 320,               // 总费用（单箱费率 × 箱数）
            perBoxFee: 0,           // 推荐承运商的单箱费率
            bestCarrier: '',        // 推荐承运商名称（最便宜）
            selectedCarrier: null,  // 用户选择的承运商对象
            carriers: [],           // 全部匹配的承运商列表
            source: '',             // 数据来源文件名
            totalMatched: 0,        // 匹配到的标准记录数
            usedLevel: '',          // 使用的数据等级（标准/参考）
            loading: false,         // 加载状态
            error: false,           // 查询失败标志
        },
        ocean: { fee: 2500, selectedCarrier: null, allCarriers: [], cheapestCarrier: null, contractRate: null, contractCarrier: '', source: '' },
        other: [],   // [{name, amount}]
        fixed: [],   // 后端返回的报关/保险等固定费用，不放进“其他费用”
        _fromRecommendation: false,
    },

    // ===== 弹窗中的推荐航线信息 =====
    routeInfoCard: { factory: '—', origin: '—', dest: '—' },

    // ===== 海运费合约报价状态（表单页与结果页共享，天然双向同步）=====
    ocean: {
        loading: false,
        error: false,
        errorDesc: '',
        realtime: false,
        carriers: [],          // 过滤后（全箱型）的船公司报价
        boxTypeKeys: [],
        medianRateText: '—',
        routeInfoText: '—',
        transitInfoText: '—',
        fetchedAtText: '—',
        factoryTagText: '—',
        shippingLineText: '—',
    },

    // ===== 推荐结果状态 =====
    results: {
        status: 'idle',        // idle | loading | error | success
        errorMsg: '',
        data: null,
        primary: null,
        alternatives: [],
        allCandidates: [],
    },
    submitting: false,
    metaText: '等待输入',
});
