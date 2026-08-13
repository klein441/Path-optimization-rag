"""
物流 RAG 数据加载 — 将 Excel 知识表与历史推荐记录转成可检索文本
"""
from __future__ import annotations

import csv
import io
import json
from pathlib import Path
from typing import Dict, List

import pandas as pd

from config import DB_ENABLED, DB_HOST, DB_PORT, DB_USER, DB_PASSWORD, DB_NAME, DB_CHARSET
from rag_config import DOCUMENTS_DIR


def _cell_text(value) -> str:
    if value is None or pd.isna(value):
        return ""
    return str(value).strip()


def _load_xlsx(path: Path) -> List[Dict]:
    docs: List[Dict] = []
    try:
        xls = pd.ExcelFile(path)
    except Exception:
        return docs
    for sheet in xls.sheet_names:
        try:
            df = pd.read_excel(path, sheet_name=sheet, dtype=str)
        except Exception:
            continue
        rows = []
        for i, row in df.iterrows():
            cells = []
            for col, val in row.items():
                text = _cell_text(val)
                if text:
                    cells.append(f"{_cell_text(col)}：{text}")
            if cells:
                rows.append((i + 2, " | ".join(cells)))
        block_size = 30
        for start in range(0, len(rows), block_size):
            block = rows[start:start + block_size]
            first_row = block[0][0]
            last_row = block[-1][0]
            lines = [
                f"文件名：{path.name}",
                f"工作表：{sheet}",
                f"行号：{first_row}-{last_row}",
            ]
            for row_no, row_text in block:
                lines.append(f"行{row_no}：{row_text}")
            content = "\n".join(lines).strip()
            if content:
                docs.append({
                    "text": content,
                    "metadata": {
                        "source": f"{path.name}/{sheet}",
                        "sheet": sheet,
                        "row_range": f"{first_row}-{last_row}",
                    },
                })
    return docs


def _load_csv(path: Path) -> List[Dict]:
    docs: List[Dict] = []
    try:
        raw = path.read_bytes()
        text = None
        for enc in ("utf-8-sig", "utf-8", "gb18030", "gbk"):
            try:
                text = raw.decode(enc)
                break
            except Exception:
                continue
        if not text:
            return docs
        sample = text[:4096]
        delimiter = ","
        try:
            dialect = csv.Sniffer().sniff(sample, delimiters=[",", "\t", ";", "|"])
            delimiter = dialect.delimiter or ","
        except Exception:
            delimiter = ","
        reader = csv.DictReader(io.StringIO(text), delimiter=delimiter)
        for i, row in enumerate(reader):
            if not row:
                continue
            lines = [f"文件名：{path.name}", f"行号：{i + 2}"]
            for k, v in row.items():
                if k is None or pd.isna(v) or str(v).strip() == "":
                    continue
                lines.append(f"{_cell_text(k)}：{_cell_text(v)}")
            content = "\n".join(lines).strip()
            if content:
                docs.append({
                    "text": content,
                    "metadata": {"source": path.name, "row": i + 2},
                })
    except Exception:
        return docs
    return docs


def _load_text_file(path: Path) -> List[Dict]:
    docs: List[Dict] = []
    try:
        raw = path.read_bytes()
        text = None
        for enc in ("utf-8-sig", "utf-8", "gb18030", "gbk"):
            try:
                text = raw.decode(enc)
                break
            except Exception:
                continue
        if text and text.strip():
            docs.append({
                "text": text.strip(),
                "metadata": {"source": path.name},
            })
    except Exception:
        return docs
    return docs


def _load_excel_and_text_files() -> List[Dict]:
    docs: List[Dict] = []
    if not DOCUMENTS_DIR.exists():
        return docs
    for path in DOCUMENTS_DIR.rglob("*"):
        if not path.is_file() or "vector_store_faiss" in path.parts:
            continue
        suffix = path.suffix.lower()
        if suffix == ".xlsx":
            docs.extend(_load_xlsx(path))
        elif suffix == ".csv":
            docs.extend(_load_csv(path))
        elif suffix in (".txt", ".md", ".json", ".log"):
            docs.extend(_load_text_file(path))
    return docs


def _safe_json(value):
    if isinstance(value, dict):
        return value
    if not isinstance(value, str):
        return {}
    try:
        return json.loads(value)
    except Exception:
        return {}


def _load_recommendation_logs() -> List[Dict]:
    if not DB_ENABLED:
        return []
    docs: List[Dict] = []
    try:
        import pymysql
        conn = pymysql.connect(
            host=DB_HOST,
            port=DB_PORT,
            user=DB_USER,
            password=DB_PASSWORD,
            database=DB_NAME,
            charset=DB_CHARSET,
            cursorclass=pymysql.cursors.DictCursor,
            autocommit=True,
        )
        try:
            with conn.cursor() as cursor:
                cursor.execute(
                    "SELECT id, created_at, input_data, output_data "
                    "FROM logistics_recommendation_log ORDER BY id DESC LIMIT 500"
                )
                rows = cursor.fetchall()
        finally:
            conn.close()
    except Exception as e:
        print(f"[RAG] 历史推荐记录加载失败: {e}")
        return docs

    for row in rows:
        input_data = _safe_json(row.get("input_data"))
        output_data = _safe_json(row.get("output_data"))
        primary = {}
        if isinstance(output_data, dict):
            primary = (output_data.get("data") or {}).get("primary") or {}
        cost = primary.get("cost") or {}
        timeline = primary.get("timeline") or {}
        lines = [
            f"历史推荐记录：{row.get('id')}",
            f"创建时间：{row.get('created_at')}",
        ]
        if input_data:
            lines.append(f"客户：{input_data.get('customer', '')}")
            lines.append(f"产品类型：{input_data.get('productType', '')}")
            lines.append(f"运抵国：{input_data.get('destCountry', '')}")
            lines.append(f"终到港：{input_data.get('destPort', '')}")
            lines.append(f"货好时间：{input_data.get('cargoReady', '')}")
            lines.append(f"要求到货时间：{input_data.get('requiredArrival', '')}")
            lines.append(f"手套数量：{input_data.get('gloveQty', '')} {input_data.get('gloveUnit', '')}")
            lines.append(f"箱数：{input_data.get('boxCount', '')}")
            lines.append(f"贸易条款：{input_data.get('tradePref', '')}")
        if primary:
            lines.append(f"主推工厂：{primary.get('factoryShort') or primary.get('factory', '')}")
            lines.append(f"起运港：{primary.get('departurePort', '')}")
            lines.append(f"终到港：{primary.get('destPort', '')}")
            lines.append(f"贸易条款：{primary.get('tradeTerm', '')}")
            lines.append(f"总费用CNY：{cost.get('totalCny', '')}")
            lines.append(f"总天数：{timeline.get('total_days') or primary.get('totalDays', '')}")
            lines.append(f"评分：{primary.get('score', '')}")
            if output_data.get("reasoning"):
                lines.append(f"推荐理由：{output_data['reasoning']}")
            if output_data.get("riskWarning"):
                lines.append(f"风险提示：{output_data['riskWarning']}")
            if output_data.get("optimizationSuggestion"):
                lines.append(f"优化建议：{output_data['optimizationSuggestion']}")
        content = "\n".join(line for line in lines if str(line).strip() and str(line).strip() != "None")
        if content:
            docs.append({
                "text": content,
                "metadata": {"source": f"历史推荐记录/{row.get('id')}"},
            })
    return docs


def _load_static_knowledge() -> List[Dict]:
    from config import FACTORY_REGION, PRODUCT_MAP, CONTRACT_BOX_COLUMNS
    lines = ["系统物流知识："]
    lines.append("工厂信息：")
    for name, info in FACTORY_REGION.items():
        lines.append(f"- {name}：地区={info.get('region')}，省份={info.get('province')}，默认港口={info.get('default_port')}")
    lines.append("产品类型：")
    for product, info in PRODUCT_MAP.items():
        lines.append(f"- {product}：匹配关键词={info.get('keyword')}")
    lines.append("柜型费率列：")
    for box, col in CONTRACT_BOX_COLUMNS.items():
        lines.append(f"- {box}：{col}")
    return [{
        "text": "\n".join(lines),
        "metadata": {"source": "系统配置知识库"},
    }]


def load_documents() -> List[Dict]:
    docs: List[Dict] = []
    docs.extend(_load_excel_and_text_files())
    docs.extend(_load_recommendation_logs())
    docs.extend(_load_static_knowledge())
    print(f"[RAG] 文档加载完成：{len(docs)} 条")
    return docs
