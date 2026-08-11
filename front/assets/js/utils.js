/**
 * 通用工具函数
 */
import { store } from './state.js';
import { EUROPEAN_COUNTRIES, PROVINCE_PORT_MAP, PORT_FACTORY_MAP, FACTORY_SHORT_MAP, OCEAN_ROUTE_MAP } from './constants.js';

export function formatDate(d) {
    if (!d) return '';
    return d.toISOString().split('T')[0];
}

export function formatFee(val) {
    return (Math.round(val * 100) / 100).toFixed(2).replace(/\.?0+$/, '') || '0';
}

export function isEuropeanCountry(country) {
    return EUROPEAN_COUNTRIES.indexOf(country) >= 0;
}

export function initDateDefaults() {
    const today = new Date();
    const in7Days = new Date(today.getTime() + 7 * 24 * 60 * 60 * 1000);
    const in14Days = new Date(today.getTime() + 14 * 24 * 60 * 60 * 1000);
    store.form.cargoReady = formatDate(in7Days);
    store.form.shipSchedule = formatDate(in14Days);
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

// 欧洲国家自动启用 ICS2 费
export function autoEnableICS2ForEurope() {
    var destCountry = store.form.destCountry || '';
    var sm = store.feeData.seaManager;
    if (isEuropeanCountry(destCountry) && !sm.ics2Enabled) {
        sm.ics2Enabled = true;
        sm.ics2Fee = 70;
    }
}