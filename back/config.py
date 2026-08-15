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
    # 以《集装箱标准容积对照表.xlsx》为准（ISO 668 及 OOCL/中远海运规格）
    "20GP": 33.2,
    "40GP": 67.7,
    "40HQ": 76.4,
    "40HC": 76.4,
    "40NOR": 67.3,
    "45HQ": 86.1,
    "20HQ": 37.5,
    "LCL": 0,  # 拼箱无固定容量
}

PORT_MISC_STANDARD_FILE = os.path.join(DATA_DIR, "港杂费标准_贸易条款承运商箱型港口.xlsx")

# 工厂到起运港拖车费（运输方式/承运商/发货工厂/始发港）— 用于陆运费推荐
ROUTE_PRICING_FILE = os.path.join(DATA_DIR, "工厂到起运港拖车费_运输方式承运商发货工厂始发港.xlsx")

# 运抵国与目的港映射表 — 用于前端运抵国/终到港下拉联动
COUNTRY_DEST_PORT_FILE = os.path.join(DATA_DIR, "运抵国与目的港.xlsx")

# 工厂分配区间规则 — 发货工厂选择的依据（表格箱数 = 千支）
FACTORY_ALLOCATION_FILE = os.path.join(DATA_DIR, "工厂分配区间规则.xlsx")

# 分析报告目录（data/report）— docx/html 报告文档，作为报告类检索知识源
REPORT_DIR = os.path.join(DATA_DIR, "report")

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

# ===== 自适应 Agentic RAG 配置 =====
# 总开关：关闭后完全走原有“规则引擎 + 单次LLM”流程
RAG_ENABLED = os.environ.get("RAG_ENABLED", "true").strip().lower() in ("1", "true", "yes")
# 语义向量开关：开启后使用本地 sentence-transformers 模型做 embedding（首次加载较慢）
# 关闭时向量检索回退到字符 n-gram 哈希相似度（纯词法），保证无重依赖可用
RAG_EMBEDDING_ENABLED = os.environ.get("RAG_EMBEDDING_ENABLED", "false").strip().lower() in ("1", "true", "yes")
EMBEDDING_MODEL = os.environ.get("EMBEDDING_MODEL", "BAAI/bge-small-zh-v1.5")
# 哈希回退向量的维度（仅 RAG_EMBEDDING_ENABLED=false 时生效）
EMBEDDING_HASH_DIM = int(os.environ.get("EMBEDDING_HASH_DIM", "512"))

# ===== 检索配置 =====
RETRIEVAL_TOP_K = int(os.environ.get("RETRIEVAL_TOP_K", "8"))
RETRIEVAL_MAX_K = int(os.environ.get("RETRIEVAL_MAX_K", "16"))
RERANK_ENABLED = os.environ.get("RERANK_ENABLED", "false").strip().lower() in ("1", "true", "yes")
# 查询扩展：命中率低时自动做同义词/翻译扩展
QUERY_EXPANSION_ENABLED = os.environ.get("QUERY_EXPANSION_ENABLED", "true").strip().lower() in ("1", "true", "yes")

# ===== Agent 配置 =====
AGENT_ENABLED = os.environ.get("AGENT_ENABLED", "true").strip().lower() in ("1", "true", "yes")
# 简单查询走快速路径（规则+检索），复杂查询才启动多步 Agent
AGENT_FASTPATH_ENABLED = os.environ.get("AGENT_FASTPATH_ENABLED", "true").strip().lower() in ("1", "true", "yes")
# 工具调用步数上限（多轮恢复/compare/exception 会用到；提高可支持更深的多轮检索）
AGENT_MAX_STEPS = int(os.environ.get("AGENT_MAX_STEPS", "8"))

# ===== 证据评分与多轮检索收敛配置 =====
# 证据覆盖率 / 置信度低于阈值时，结果标记 needs_review（需人工复核）
EVIDENCE_TARGET_COVERAGE = float(os.environ.get("EVIDENCE_TARGET_COVERAGE", "0.6"))
EVIDENCE_MIN_CONFIDENCE = float(os.environ.get("EVIDENCE_MIN_CONFIDENCE", "0.5"))
# 多轮检索收敛：每轮证据分数提升低于该值则停止继续检索
EVIDENCE_CONVERGE_EPS = float(os.environ.get("EVIDENCE_CONVERGE_EPS", "0.03"))

# ===== 反馈学习配置 =====
# 是否自动把用户反馈应用为评分权重（默认 false：只记录，人工审核后再应用）
FEEDBACK_AUTO_APPLY = os.environ.get("FEEDBACK_AUTO_APPLY", "false").strip().lower() in ("1", "true", "yes")

# ===== 会话记忆配置 =====
SESSION_TTL = int(os.environ.get("SESSION_TTL", "1800"))        # 会话上下文保留秒数
SESSION_MAX_TURNS = int(os.environ.get("SESSION_MAX_TURNS", "10"))  # 每会话最多保留轮数

# ===== LLM 路由配置 =====
# 关键词无法确定意图（意图为 None / follow_up）时，调用 LLM 做意图分类（LLM 未启用时自动回退关键词）
LLM_ROUTING_ENABLED = os.environ.get("LLM_ROUTING_ENABLED", "true").strip().lower() in ("1", "true", "yes")
# 反馈调权缓存文件（离线脚本计算后写入，运行时加载）
FEEDBACK_WEIGHTS_CACHE = os.path.join(DATA_DIR, "feedback_weights.json")