/**
 * 通用工具函数
 */
import { store } from './state.js';
import { EUROPEAN_COUNTRIES, PROVINCE_PORT_MAP, PORT_FACTORY_MAP, FACTORY_SHORT_MAP, OCEAN_ROUTE_MAP } from './constants.js';

export function formatDate(d) {
    if (!d) return '';
    const y = d.getFullYear();
    const m = String(d.getMonth() + 1).padStart(2, '0');
    const day = String(d.getDate()).padStart(2, '0');
    return `${y}-${m}-${day}`;
}

export function formatFee(val) {
    return (Math.round(val * 100) / 100).toFixed(2).replace(/\.?0+$/, '') || '0';
}

export function isEuropeanCountry(country) {
    return EUROPEAN_COUNTRIES.indexOf(country) >= 0;
}

export function isFTradeTerm(term) {
    var t = String(term || '').trim().toUpperCase();
    return t === 'FOB' || t === 'FCA' || t === 'FAS';
}

export function initDateDefaults() {
    const today = new Date();
    const inOneMonth = new Date(today);
    inOneMonth.setMonth(inOneMonth.getMonth() + 1);
    store.form.cargoReady = formatDate(today);
    store.form.requiredArrival = formatDate(inOneMonth);
}

// 更新顶部结果状态栏（metaText 带 5 秒自动还原）
export function showNotification(msg) {
    store.metaText = '✓ ' + String(msg).split('！')[0];
    const original = store.metaText;
    setTimeout(() => {
        if (store.metaText === original) store.metaText = '推荐方案';
    }, 5000);
}

// 根据目的国和始发港推断最可能的发货工厂（回退方案）
export function getFallbackFactory(originPort) {
    var factory = PORT_FACTORY_MAP[originPort] || '安徽英科医疗用品有限公司';
    return { factory: factory, factoryShort: FACTORY_SHORT_MAP[factory] || factory };
}

// 根据目的国获取标准航线港口（回退方案，仅在后端 /api/route-info 不可用时使用）
export function getOceanPortsByCountry(country) {
    if (country && OCEAN_ROUTE_MAP[country]) return OCEAN_ROUTE_MAP[country];
    return { origin: '上海/SHANGHAI', destination: '洛杉矶/LOS ANGELES' };
}

// 根据省份回退推断始发港（高速费计算用）
export function getOriginPortByProvince(province) {
    return PROVINCE_PORT_MAP[province] || '上海/SHANGHAI';
}

// 欧盟/欧洲经济区自动启用 ICS2 费，固定70元
export function autoEnableICS2ForEurope() {
    var destCountry = store.form.destCountry || '';
    var sm = store.feeData.seaManager;
    if (isEuropeanCountry(destCountry)) {
        sm.ics2Enabled = true;
        sm.ics2Fee = 70;
    } else {
        sm.ics2Enabled = false;
        sm.ics2Fee = 0;
    }
}
