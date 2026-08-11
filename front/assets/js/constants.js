/**
 * 常量定义 — 物流运输路径智能优化系统
 */

// ===== API 配置 =====
export const API_BASE = 'http://localhost:5000';

// ===== 运输方式推荐陆运费 =====
export const TRANSPORT_MODE_FREIGHT = {
    direct:     { label: '直拖',     baseFreight: 500, hasToll: false },
    seaRail:    { label: '海铁',     baseFreight: 300, hasToll: false },
    factorySelf:{ label: '工厂自运', baseFreight: 200, hasToll: true },
    landToWater:{ label: '陆改水',   baseFreight: 400, hasToll: false },
};

// ===== 集装箱箱型固定体积（m³）=====
export const BOX_VOLUMES = {
    "20GP": 33.1, "20HQ": 33.1,
    "40GP": 67.5, "40HQ": 76.0, "40HC": 76.0,
    "40NOR": 67.5,
    "45HQ": 85.0,
};

// ===== 产品类型选项 =====
export const PRODUCT_OPTIONS = [
    { value: '丁腈手套', label: '丁腈手套' },
    { value: 'PVC手套',  label: 'PVC手套' },
];

// ===== 箱型选项（含展示标签）=====
export const BOX_TYPE_OPTIONS = [
    { value: '20GP',  label: '20GP（20英尺标准箱 · 33.1m³）' },
    { value: '20HQ',  label: '20HQ（20英尺高柜 · 33.1m³）' },
    { value: '40GP',  label: '40GP（40英尺标准箱 · 67.5m³）' },
    { value: '40HQ',  label: '40HQ（40英尺高柜 · 76m³）' },
    { value: '40HC',  label: '40HC（40英尺高柜 · 76m³）' },
    { value: '45HQ',  label: '45HQ（45英尺高柜 · 85m³）' },
    { value: '40NOR', label: '40NOR（40英尺冷代干 · 67.5m³）' },
];

// ===== 欧洲国家列表 =====
export const EUROPEAN_COUNTRIES = [
    '德国', '荷兰', '英国', '法国', '意大利', '西班牙', '比利时', '波兰',
    '瑞典', '芬兰', '丹麦', '奥地利', '爱尔兰', '葡萄牙', '希腊',
    '捷克', '罗马尼亚', '匈牙利', '斯洛文尼亚', '爱沙尼亚', '立陶宛',
    '克罗地亚', '拉脱维亚', '保加利亚', '斯洛伐克', '卢森堡', '马耳他',
    '塞浦路斯', '挪威', '瑞士'
];

// ===== 始发港 → 工厂 回退映射 =====
export const PORT_FACTORY_MAP = {
    '青岛/QINGDAO': '山东英科医疗制品有限公司',
    '上海/SHANGHAI': '安徽英科医疗用品有限公司',
    '深圳/SHENZHEN': '江西英科医疗有限公司',
    '海防/HAIPHONG': 'BASIC INTERNATIONAL VIET NAM CO..LTD',
    '勿拉湾/BELAWAN': 'PT BASIC INTERNATIONAL SUMATERA',
};

export const FACTORY_SHORT_MAP = {
    '山东英科医疗制品有限公司': '山东英科',
    '安徽英科医疗用品有限公司': '安徽英科',
    '江西英科医疗有限公司': '江西英科',
    'BASIC INTERNATIONAL VIET NAM CO..LTD': '越南英科',
    'PT BASIC INTERNATIONAL SUMATERA': '印尼英科',
};

// ===== 目的国 → 标准航线港口（回退方案）=====
export const OCEAN_ROUTE_MAP = {
    '美国': { origin: '青岛/QINGDAO', destination: '洛杉矶/LOS ANGELES' },
    '加拿大': { origin: '青岛/QINGDAO', destination: '洛杉矶/LOS ANGELES' },
    '墨西哥': { origin: '青岛/QINGDAO', destination: '洛杉矶/LOS ANGELES' },
    '英国': { origin: '上海/SHANGHAI', destination: '鹿特丹/ROTTERDAM' },
    '德国': { origin: '上海/SHANGHAI', destination: '汉堡/HAMBURG' },
    '法国': { origin: '上海/SHANGHAI', destination: '鹿特丹/ROTTERDAM' },
    '荷兰': { origin: '上海/SHANGHAI', destination: '鹿特丹/ROTTERDAM' },
    '比利时': { origin: '上海/SHANGHAI', destination: '安特卫普/ANTWERP' },
    '意大利': { origin: '上海/SHANGHAI', destination: '鹿特丹/ROTTERDAM' },
    '西班牙': { origin: '上海/SHANGHAI', destination: '鹿特丹/ROTTERDAM' },
    '澳大利亚': { origin: '上海/SHANGHAI', destination: '悉尼/SYDNEY' },
    '新西兰': { origin: '上海/SHANGHAI', destination: '墨尔本/MELBOURNE' },
    '日本': { origin: '上海/SHANGHAI', destination: '东京/TOKYO' },
    '韩国': { origin: '青岛/QINGDAO', destination: '釜山/BUSAN' },
    '新加坡': { origin: '深圳/SHENZHEN', destination: '新加坡' },
    '马来西亚': { origin: '深圳/SHENZHEN', destination: '巴生港/PORT KLANG' },
    '泰国': { origin: '深圳/SHENZHEN', destination: '新加坡' },
    '印度尼西亚': { origin: '深圳/SHENZHEN', destination: '勿拉湾/BELAWAN' },
    '越南': { origin: '深圳/SHENZHEN', destination: '海防/HAIPHONG' },
    '印度': { origin: '上海/SHANGHAI', destination: '迪拜/DUBAI' },
    '阿联酋': { origin: '上海/SHANGHAI', destination: '迪拜/DUBAI' },
    '沙特阿拉伯': { origin: '上海/SHANGHAI', destination: '迪拜/DUBAI' },
    '巴西': { origin: '上海/SHANGHAI', destination: '洛杉矶/LOS ANGELES' },
};

// ===== 省份 → 始发港 回退映射（高速费计算用）=====
export const PROVINCE_PORT_MAP = {
    '山东': '青岛/QINGDAO', '安徽': '上海/SHANGHAI', '江西': '上海/SHANGHAI',
    '江苏': '上海/SHANGHAI', '上海': '上海/SHANGHAI',
};