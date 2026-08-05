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
# 7 个基础数据文件（实际存在于 data 目录）
FILES = {
    # 1. 各基地产能 — 工厂PVC/丁腈手套产能数据
    "factory_capacity": os.path.join(DATA_DIR, "各基地产能.xlsx"),
    # 2. 海运费收入 — 发票号、海运费、客户海运费、海运费收入
    "shipping_fee": os.path.join(DATA_DIR, "海运费收入.xlsx"),
    # 3. 费用 — 38404条费用明细（费用大类/类型/金额）
    "costs": os.path.join(DATA_DIR, "费用.xlsx"),
    # 4. 集装箱运单 — 箱型/箱数/毛重/体积/装柜日期/承运商
    "container_waybill": os.path.join(DATA_DIR, "集装箱运单.xlsx"),
    # 5. 物料行 — 物料名称/数量/重量/体积/发货车间/付款方式
    "material_line": os.path.join(DATA_DIR, "物料行.xlsx"),
    # 6. 提单运单 — 客户/运抵国/贸易条款/始发港/目的港/发货工厂/时间
    #    作为核心数据源，替代原"出口销售订单"的功能
    "bl_waybill": os.path.join(DATA_DIR, "提单运单.xlsx"),
    # 7. TMS费用类型 — 83种费用类型定义（费用大类/费用类型映射）
    "tms_fee_type": os.path.join(DATA_DIR, "TMS费用类型.xlsx"),
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
USD_TO_CNY = float(os.environ.get("USD_TO_CNY", "7.2"))
CNY_TO_USD = 1.0 / USD_TO_CNY

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
    "安徽英科医疗用品有限公司": {"region": "国内", "province": "安徽", "default_port": "青岛/QINGDAO"},
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
