# 物流运输路径智能优化系统

基于现有业务系统和运输数据，建立外销物流运输路径优化模型，从运输成本、运输时效、运输稳定性等多个维度进行综合分析。

## 项目结构

```
Path optimization/
├── back/                       # 后端代码
│   ├── app.py                  # Flask API 服务器
│   ├── config.py               # 配置文件（路径、LLM、汇率等）
│   ├── data_loader.py          # 数据加载器（7张Excel表）
│   ├── knowledge_base.py       # 知识库（工厂、港口、费用统计）
│   ├── cost_calculator.py      # 费用计算器
│   ├── llm_client.py           # LLM客户端（含规则引擎降级）
│   └── recommendation_engine.py # 推荐引擎
├── front/                      # 前端代码（Vue 3 模块化）
│   ├── logistics-optimizer.html # 主页面（Vue 入口）
│   └── assets/
│       ├── css/               # 样式（按模块拆分）
│       ├── vendor/            # Vue 3 本地 ESM（无构建）
│       └── js/                # JS 模块
│           ├── constants.js   # 常量
│           ├── state.js       # 全局响应式状态
│           ├── api.js         # API 请求封装
│           ├── fees.js        # 费用计算
│           ├── ocean.js       # 海运费合约比价
│           ├── submit.js      # 提交 / 重新优化
│           ├── utils.js       # 工具函数
│           ├── App.js         # 根组件
│           ├── main.js        # 入口
│           └── components/    # Vue 组件（表单/结果/费用面板/弹窗等）
├── data/                       # 数据文件（Excel）
│   ├── 各基地产能.xlsx
│   ├── 海运费收入.xlsx
│   ├── 费用.xlsx
│   ├── 集装箱运单.xlsx
│   ├── 物料行.xlsx
│   ├── 提单运单.xlsx
│   └── TMS费用类型.xlsx
├── main.py                     # 启动入口
└── requirements.txt            # 依赖清单
```

## 快速开始

### 1. 安装依赖

```bash
cd "d:\Path optimization"
pip install -r requirements.txt
```

### 2. 启动服务

```bash
python main.py
```

服务启动后访问：
- 后端 API: `http://localhost:5000`
- 前端页面: 启动服务后访问 `http://localhost:5000`（前端为 ES Modules，需经 HTTP 访问）

### 3. 配置 LLM（可选）

如需启用 LLM 智能推荐，设置环境变量：

```bash
# Windows PowerShell
$env:LLM_API_KEY = "your-api-key-here"

# 然后重新启动
python main.py
```

## API 接口

| 方法 | 路径 | 说明 |
|------|------|------|
| POST | `/api/logistics/recommend` | 获取推荐方案 |
| GET | `/api/logistics/health` | 健康检查 |
| GET | `/api/logistics/knowledge` | 知识库摘要 |
| GET | `/api/logistics/factories` | 工厂列表及产能 |
| GET | `/api/logistics/countries` | 支持的运抵国 |

## 推荐接口示例

```json
// POST /api/logistics/recommend
{
  "customer": "Medline Inc.",
  "productType": "丁腈手套",
  "destCountry": "美国",
  "boxCount": 800,
  "weight": 12000,
  "volume": 68,
  "cargoReady": "2026-08-15",
  "shipSchedule": "2026-08-20",
  "transportPref": "balanced",
  "tradePref": "auto"
}
```

## 技术架构

- **后端**: Flask + Pandas + NumPy
- **前端**: Vue 3（本地 ES Modules，无构建工具）+ 模块化 JS / 拆分 CSS
- **LLM**: 可选，支持任何兼容 OpenAI API 的模型
- **数据源**: 7 张 Excel 表格（提单运单、物料行、集装箱运单、费用明细、海运费收入、各基地产能、TMS费用类型）
- **核心引擎**: 规则引擎（始终可用）+ LLM 增强（有API Key时）
