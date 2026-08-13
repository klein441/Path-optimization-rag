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
│   ├── 海运费参考标准.xlsx          （原合约信息导出0806）
│   ├── 工厂到起运港拖车费_运输方式承运商发货工厂始发港.xlsx  （原各路线报价卡）
│   ├── 工厂到起运港时效分析表.xlsx
│   ├── 工厂分配区间规则.xlsx
│   ├── 港杂费标准_贸易条款承运商箱型港口.xlsx
│   ├── 运抵国与目的港.xlsx
│   └── 集装箱标准容积对照表.xlsx
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
python back\app.py
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
python back\app.py
```

### 4. 连接 MySQL（可选）

后端会把每次推荐的输入和输出结果写入 MySQL，未配置时不影响正常推荐。

```powershell
$env:DB_ENABLED = "true"
$env:DB_HOST = "127.0.0.1"
$env:DB_PORT = "3306"
$env:DB_USER = "root"
$env:DB_PASSWORD = "your-password"
$env:DB_NAME = "logistics_optimizer"
python back\app.py
```

首次启动会自动创建表 `logistics_recommendation_log`，字段包含输入 JSON、输出 JSON、推荐工厂、始发港、终到港、贸易条款、总费用、时效和评分。

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
- **数据源**: 本地 Excel 数据表（工厂分配区间规则、海运费参考标准、工厂到起运港拖车费、港杂费标准、运抵国与目的港等）
- **选线逻辑**: 按《工厂分配区间规则》匹配物料大类和箱数（千支）确定首选/备选1/备选2 三个发货工厂；每个工厂取《港口发货明细》中的全部历史常用始发港，需要海运费时只保留《海运费参考标准》有报价的路线；若过滤后候选路线为 0，则退回合约海运费 Top5；再枚举工厂×始发港组合计算全费用
- **核心引擎**: 规则引擎（始终可用）+ LLM 增强（有API Key时）
