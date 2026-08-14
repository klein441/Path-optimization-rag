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
        productSizes: {},        // { "丁腈手套": ["M","L"], "PVC手套": ["L"] }
        boxTypes: [],            // 选中的柜型
        boxTypeCounts: {},       // { "40HQ": 5, "20GP": 3 }
        destCountry: '',
        destPort: '',
        gloveQty: 1000,
        gloveUnit: '千支',
        gloveQuantities: {},   // { "丁腈手套": { "M": 100, "L": 100 } }
        gloveQtyPanelOpen: false,
        cargoReady: '',
        requiredArrival: '',
        urgent: false,
        tradePref: 'FOB',
        transportPref: 'auto',
        remarks: '',
        // 派生值（由 OrderForm watcher 同步）
        boxes: 1,
        volume: 0,
        volumeHint: '请先选择集装箱柜型',
        weight: 0,
    },

    // ===== 动态下拉数据 =====
    countries: [],
    countriesLoading: true,
    destPorts: [],
    destPortsLoading: false,

    // ===== UI 开关 =====
    advancedOpen: true,
    feeConfirmed: false, // 费用信息是否已确认（结果页锁定费用输入）
    lastSubmitPayload: null, // 最近一次推荐请求的原始载荷，用于费用确认时回写数据库
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
            perBoxFee: 0,           // 推荐承运商的单柜费率
            recommendedRatesByType: {},    // { "40HQ": 5000, "20GP": 4000 }
            selectedRatesByType: {},       // 用户选择的各柜型单柜费率
            selectedCarrierByType: {},     // 用户选择的各柜型承运商
            source: '',             // 数据来源
            totalMatched: 0,        // 匹配记录数
            loading: false,
            error: false,
        },
        seaManager: { manifestFee: 55, manifestCustom: 0, manifestMode: '55', vgmFee: 5, ics2Enabled: false, ics2Fee: 0 },
        portMisc: {
            fee: 320,               // 总费用（单柜费率 × 柜数）
            perBoxFee: 0,           // 推荐承运商的单柜费率
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
        carriers: [],          // 过滤后（全柜型）的船公司报价
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
