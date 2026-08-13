"""
配置文件 — 物流运输路径智能优化后端
"""
import os
from dotenv import load_dotenv

# 加载项目根目录的 .env 文件
_BASE_DIR = os.path.dirname(os.path.abspath(__file__))
_ROOT_DIR = os.path.dirname(_BASE_DIR)
load_dotenv(os.path.join(_ROOT_DIR, ".env"))

# ===== 路径配置 =====
BASE_DIR = _BASE_DIR
DATA_DIR = os.path.join(_ROOT_DIR, "data")

# ===== 数据源文件路径 =====
# 当前仅使用《工厂分配区间规则》
FILES = {
    "allocation_rules": os.path.join(DATA_DIR, "工厂分配区间规则.xlsx"),
}

# ===== LLM 配置 =====
LLM_API_URL = os.environ.get("LLM_API_URL", "https://api.deepseek.com/v1/chat/completions")
LLM_API_KEY = os.environ.get("LLM_API_KEY", "")
LLM_MODEL = os.environ.get("LLM_MODEL", "deepseek-chat")
LLM_TIMEOUT = int(os.environ.get("LLM_TIMEOUT", "60"))
LLM_ENABLED = bool(LLM_API_KEY)

# ===== 服务配置 =====
HOST = os.environ.get("HOST", "0.0.0.0")
PORT = int(os.environ.get("PORT", "5000"))
CORS_ORIGINS = os.environ.get("CORS_ORIGINS", "*")

# ===== 汇率配置 =====
USD_TO_CNY = float(os.environ.get("USD_TO_CNY", "6.747"))
CNY_TO_USD = 1.0 / USD_TO_CNY

# ===== MySQL 配置 =====
DB_ENABLED = os.environ.get("DB_ENABLED", "false").strip().lower() in ("1", "true", "yes")
DB_HOST = os.environ.get("DB_HOST", "127.0.0.1")
DB_PORT = int(os.environ.get("DB_PORT", "3306"))
DB_USER = os.environ.get("DB_USER", "root")
DB_PASSWORD = os.environ.get("DB_PASSWORD", "")
DB_NAME = os.environ.get("DB_NAME", "logistics_optimizer")
DB_CHARSET = os.environ.get("DB_CHARSET", "utf8mb4")

# ===== 产品类型映射 =====
# 前端产品类型 -> 数据库物料类型关键词
PRODUCT_MAP = {
    "丁腈手套": {"keyword": "丁腈", "capacity_field": "丁腈数量（千只数）"},
    "PVC手套": {"keyword": "PVC", "capacity_field": "PVC数量（千只数）"},
    "PE产品": {"keyword": "PE", "capacity_field": None},
    "轮椅": {"keyword": "轮椅", "capacity_field": None},
    "小日化产品": {"keyword": "日化", "capacity_field": None},
}

# ===== 工厂简称映射 =====
FACTORY_SHORT = {
    "安徽英科医疗用品有限公司": "安徽英科",
    "山东英科医疗制品有限公司": "山东英科",
    "江西英科医疗有限公司": "江西英科",
    "安庆英科医疗有限公司": "安庆英科",
    "英科医疗科技股份有限公司": "英科医疗科技",
    "山东英科医疗科技有限公司": "山东医疗科技",
    "上海英恩国际贸易有限公司": "上海英恩",
    "上海英科心电图医疗产品有限公司": "上海英科心电图",
    "上海英科医疗用品有限公司": "上海英科医疗",
    "江苏英科医疗制品有限公司": "江苏英科",
    "BASIC INTERNATIONAL VIET NAM CO..LTD": "越南英科",
    "INTCO MEDICAL TECHNOLOGY VIET NAM COMPANY LIMITED": "越南医疗科技",
    "PT BASIC INTERNATIONAL SUMATERA": "印尼英科",
    "山东英彩印刷科技有限公司": "山东英彩",
    "山东英科卫生用品有限公司": "山东卫生用品",
}

# ===== 工厂所在地/区域映射 =====
FACTORY_REGION = {
    "安徽英科医疗用品有限公司": {"region": "国内", "province": "安徽", "default_port": "上海/SHANGHAI"},
    "山东英科医疗制品有限公司": {"region": "国内", "province": "山东", "default_port": "青岛/QINGDAO"},
    "江西英科医疗有限公司": {"region": "国内", "province": "江西", "default_port": "上海/SHANGHAI"},
    "安庆英科医疗有限公司": {"region": "国内", "province": "安徽", "default_port": "上海/SHANGHAI"},
    "英科医疗科技股份有限公司": {"region": "国内", "province": "山东", "default_port": "青岛/QINGDAO"},
    "山东英科医疗科技有限公司": {"region": "国内", "province": "山东", "default_port": "青岛/QINGDAO"},
    "上海英恩国际贸易有限公司": {"region": "国内", "province": "上海", "default_port": "上海/SHANGHAI"},
    "上海英科心电图医疗产品有限公司": {"region": "国内", "province": "上海", "default_port": "上海/SHANGHAI"},
    "上海英科医疗用品有限公司": {"region": "国内", "province": "上海", "default_port": "上海/SHANGHAI"},
    "江苏英科医疗制品有限公司": {"region": "国内", "province": "江苏", "default_port": "上海/SHANGHAI"},
    "BASIC INTERNATIONAL VIET NAM CO..LTD": {"region": "海外", "province": "越南", "default_port": "海防/HAIPHONG"},
    "INTCO MEDICAL TECHNOLOGY VIET NAM COMPANY LIMITED": {"region": "海外", "province": "越南", "default_port": "海防/HAIPHONG"},
    "PT BASIC INTERNATIONAL SUMATERA": {"region": "海外", "province": "印尼", "default_port": "勿拉湾/BELAWAN"},
}

# ===== 北美市场国家 =====
NORTH_AMERICA = ["美国", "加拿大", "墨西哥"]

# ===== FDA要求国家 =====
FDA_COUNTRIES = ["美国"]

# ===== 合约海运费数据文件（原《合约信息导出0806》）=====
CONTRACT_FREIGHT_FILE = os.path.join(DATA_DIR, "海运费参考标准.xlsx")
# 合约海运费缓存刷新间隔（秒），默认 1 小时
CONTRACT_FREIGHT_CACHE_TTL = 3600
# 合约箱型列名映射（前端箱型 -> Excel 列名）
CONTRACT_BOX_COLUMNS = {
    "20GP": "20GP报价",
    "40GP": "40GP报价",
    "40HQ": "40HC报价",
    "45HQ": "45HC报价",
    "40HC": "40HC报价",
    "45HC": "45HC报价",
}
# 箱型 -> 计费单位
CONTRACT_BOX_UNIT = {
    "20GP": "TEU",
    "40GP": "FEU",
    "40HQ": "FEU",
    "45HQ": "FEU",
}

# ===== 集装箱箱型标准容量（CBM） =====
BOX_TYPE_VOLUME = {
    "20GP": 33.1,
    "40GP": 67.5,
    "40HQ": 76.0,
    "40HC": 76.0,
    "40NOR": 67.5,
    "45HQ": 85.0,
    "20HQ": 33.1,
    "LCL": 0,  # 拼箱无固定容量
}

PORT_MISC_STANDARD_FILE = os.path.join(DATA_DIR, "港杂费标准_贸易条款承运商箱型港口.xlsx")

# 工厂到起运港拖车费（运输方式/承运商/发货工厂/始发港）— 用于陆运费推荐
ROUTE_PRICING_FILE = os.path.join(DATA_DIR, "工厂到起运港拖车费_运输方式承运商发货工厂始发港.xlsx")

# 运抵国与目的港映射表 — 用于前端运抵国/终到港下拉联动
COUNTRY_DEST_PORT_FILE = os.path.join(DATA_DIR, "运抵国与目的港.xlsx")

# 工厂分配区间规则 — 发货工厂选择的依据（表格箱数 = 千支）
FACTORY_ALLOCATION_FILE = os.path.join(DATA_DIR, "工厂分配区间规则.xlsx")

# ===== 国内始发港（11个）用于海运费比价选出最优5港 =====
# 中文名 → 标准格式（中文/英文），用于合约匹配和费用计算
DOMESTIC_ORIGIN_PORTS = {
    "青岛": "青岛/QINGDAO",
    "上海": "上海/SHANGHAI",
    "宁波": "宁波/NINGBO",
    "九江": "九江/JIUJIANG",
    "镇江": "镇江/ZHENJIANG",
    "香港": "香港/HONGKONG",
    "深圳": "深圳/SHENZHEN",
    "连云港": "连云港/LIANYUNGANG",
    "南京": "南京/NANJING",
    "厦门": "厦门/XIAMEN",
    "天津": "天津/TIANJIN",
}

# 工厂分配区间规则中的工厂名 → 系统内部工厂名
FACTORY_ALLOCATION_NAME_MAP = {
    "淮北PVC": "安徽英科医疗用品有限公司",
    "淮北丁腈": "安徽英科医疗用品有限公司",
    "青州PVC": "山东英科医疗制品有限公司",
    "青州丁腈": "山东英科医疗制品有限公司",
    "淄博PVC": "英科医疗科技股份有限公司",
    "江西丁腈": "江西英科医疗有限公司",
    "安庆丁腈": "安庆英科医疗有限公司",
    "清化丁腈": "BASIC INTERNATIONAL VIET NAM CO..LTD",
    "张店PE": "山东英科医疗科技有限公司",
    "广宁PE": "BASIC INTERNATIONAL VIET NAM CO..LTD",
}
