"""
RAG 知识库存储 — 自适应 Agentic RAG 的检索底座

职责：
1. 把 8 张 Excel 数据表 + KnowledgeBase 知识切分为可检索的 Chunk（带 metadata）
2. 构建关键词索引（纯 Python BM25 风格）与可选语义向量索引（sentence-transformers）
3. 提供混合检索接口 search()

设计原则：
- 不引入重依赖：向量库使用内存 numpy 矩阵；无 embedding 模型时回退到字符 n-gram 哈希相似度
- 语义向量开关：RAG_EMBEDDING_ENABLED=true 时才加载模型（首次较慢）
- 数据变更检测：Excel 文件 mtime 变化时增量重建
"""
import os
import re
import json
import time
import hashlib
from collections import Counter
from dataclasses import dataclass, field, asdict

import numpy as np
import pandas as pd

import config
from knowledge_base import KnowledgeBase


# ===== 分块 =====
@dataclass
class Chunk:
    chunk_id: str
    source: str        # 数据源文件/名称
    chunk_type: str    # rule / quote / fee / land_freight / transit_time / mapping / constant / knowledge / history
    text: str          # 检索用文本
    metadata: dict = field(default_factory=dict)
    embedding: object = None  # np.ndarray（可选）
    score: float = 0.0

    def to_dict(self, include_embedding=False):
        d = asdict(self)
        if not include_embedding:
            d.pop("embedding", None)
        return d


# ===== 分词 =====
_CJK_RE = re.compile(r"[\u4e00-\u9fff]")


def tokenize(text):
    """中英混合分词：英文按词，中文按双字 bigram（不重叠）"""
    text = str(text or "").lower()
    toks = re.findall(r"[a-z0-9]+", text)
    # 中文：逐对相邻字符生成 bigram
    cjk = _CJK_RE.findall(text)
    if len(cjk) >= 2:
        toks.extend(cjk[i] + cjk[i + 1] for i in range(len(cjk) - 1))
    return toks


def _row_text(df, row, cols=None):
    """把一行 DataFrame 转成 '列名: 值' 的可检索文本"""
    parts = []
    for col in (cols or df.columns):
        val = row.get(col)
        if val is None or (isinstance(val, float) and np.isnan(val)):
            continue
        s = str(val).strip()
        if s and s.lower() != "nan":
            parts.append(f"{col}: {s}")
    return " | ".join(parts)


# ===== 哈希回退向量（无 embedding 模型时）=====
def _hash_embed(texts, dim=512):
    vecs = np.zeros((len(texts), dim), dtype=np.float32)
    for i, t in enumerate(texts):
        toks = tokenize(t) or ["<pad>"]
        for tok in toks:
            h = int(hashlib.md5(tok.encode("utf-8")).hexdigest(), 16)
            vecs[i, h % dim] += 1.0
        norm = np.linalg.norm(vecs[i])
        if norm > 0:
            vecs[i] /= norm
    return vecs


class _Embedder:
    """惰性加载的语义向量编码器（单例）"""
    _model = None
    _model_name = None

    @classmethod
    def encode(cls, texts, model_name):
        if cls._model is None or cls._model_name != model_name:
            from sentence_transformers import SentenceTransformer
            print(f"[RAG] 加载 embedding 模型: {model_name} ...")
            cls._model = SentenceTransformer(model_name)
            cls._model_name = model_name
        return cls._model.encode(
            list(texts), normalize_embeddings=True, show_progress_bar=False,
            batch_size=64,
        )


# ===== 检索器 =====
class RagStore:
    """内存向量/关键词混合检索库"""

    _instance = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._built = False
        return cls._instance

    def __init__(self):
        self.chunks = []
        self._chunk_tokens = []          # list[Counter]
        self._idf = {}                   # token -> idf
        self._embeddings = None          # np.ndarray (n, dim) or None
        self._file_mtimes = {}
        self._embedding_enabled = False
        self._built_at = None

    # ===== 构建 =====
    def build(self, force=False, embedding_enabled=None):
        if self._built and not force:
            return
        print("[RAG] 开始构建检索知识库...")
        t0 = time.time()
        self._embedding_enabled = config.RAG_EMBEDDING_ENABLED if embedding_enabled is None else embedding_enabled

        kb = KnowledgeBase()
        kb.build()

        chunks = []
        chunks += self._chunk_allocation_rules()
        chunks += self._chunk_contract_freight()
        chunks += self._chunk_port_misc_fee()
        chunks += self._chunk_route_pricing()
        chunks += self._chunk_time_analysis()
        chunks += self._chunk_country_dest_ports()
        chunks += self._chunk_box_volume()
        chunks += self._chunk_kb_knowledge(kb)
        chunks += self._chunk_report_docs()

        # 去重（同 source+text）
        seen = set()
        deduped = []
        for c in chunks:
            key = (c.source, c.text)
            if key in seen:
                continue
            seen.add(key)
            deduped.append(c)

        self.chunks = deduped
        self._build_keyword_index()
        self._build_embeddings()
        self._record_file_mtimes()
        self._built = True
        self._built_at = time.strftime("%Y-%m-%d %H:%M:%S")
        print(f"[RAG] 检索库构建完成: {len(self.chunks)} chunks, 耗时 {time.time() - t0:.1f}s, "
              f"embedding={'semantic' if self._embedding_enabled else 'hash-fallback'}")

    # ===== 各数据源分块 =====
    def _chunk_allocation_rules(self):
        out = []
        fpath = config.FACTORY_ALLOCATION_FILE
        try:
            try:
                df = pd.read_excel(fpath, sheet_name="工厂分配规则")
            except Exception:
                df = pd.read_excel(fpath, sheet_name=0)
            for idx, (_, row) in enumerate(df.iterrows()):
                text = _row_text(df, row)
                if not text:
                    continue
                out.append(Chunk(
                    chunk_id=f"rule_{idx}",
                    source=os.path.basename(fpath),
                    chunk_type="rule",
                    text=f"[工厂分配规则] {text}",
                    metadata={"material": str(row.get("物料大类", "") or "").strip(),
                              "factory": str(row.get("首选工厂", "") or "").strip()},
                ))
        except Exception as e:
            print(f"[RAG] 分块失败 {fpath}: {e}")

        # 港口发货明细（历史出货统计）
        try:
            detail = pd.read_excel(fpath, sheet_name="港口发货明细")
            for idx, (_, row) in enumerate(detail.iterrows()):
                text = _row_text(detail, row)
                if not text:
                    continue
                out.append(Chunk(
                    chunk_id=f"history_{idx}",
                    source=os.path.basename(fpath),
                    chunk_type="history",
                    text=f"[港口发货历史] {text}",
                    metadata={"factory": str(row.get("发货工厂", "") or "").strip(),
                              "port": str(row.get("始发港", "") or "").strip()},
                ))
        except Exception as e:
            print(f"[RAG] 港口发货明细分块失败: {e}")
        return out

    def _chunk_contract_freight(self):
        out = []
        fpath = config.CONTRACT_FREIGHT_FILE
        if not os.path.exists(fpath):
            return out
        try:
            df = pd.read_excel(fpath, sheet_name=0)
            for idx, (_, row) in enumerate(df.iterrows()):
                text = _row_text(df, row)
                if not text:
                    continue
                out.append(Chunk(
                    chunk_id=f"quote_{idx}",
                    source=os.path.basename(fpath),
                    chunk_type="quote",
                    text=f"[海运费合约报价] {text}",
                    metadata={"origin_port": str(row.get("起运港", "") or "").strip(),
                              "dest_port": str(row.get("目的港", "") or "").strip(),
                              "carrier": str(row.get("船公司简称", "") or "").strip()},
                ))
        except Exception as e:
            print(f"[RAG] 分块失败 {fpath}: {e}")
        return out

    def _chunk_port_misc_fee(self):
        out = []
        fpath = config.PORT_MISC_STANDARD_FILE
        if not os.path.exists(fpath):
            return out
        try:
            df = pd.read_excel(fpath, sheet_name=0)
            for idx, (_, row) in enumerate(df.iterrows()):
                text = _row_text(df, row)
                if not text:
                    continue
                out.append(Chunk(
                    chunk_id=f"fee_{idx}",
                    source=os.path.basename(fpath),
                    chunk_type="fee",
                    text=f"[港杂费标准] {text}",
                    metadata={"port": str(row.get("港口", "") or row.get("起运港", "") or "").strip(),
                              "term": str(row.get("贸易条款", "") or "").strip()},
                ))
        except Exception as e:
            print(f"[RAG] 分块失败 {fpath}: {e}")
        return out

    def _chunk_route_pricing(self):
        out = []
        fpath = config.ROUTE_PRICING_FILE
        if not os.path.exists(fpath):
            return out
        try:
            df = pd.read_excel(fpath, sheet_name=0)
            for idx, (_, row) in enumerate(df.iterrows()):
                text = _row_text(df, row)
                if not text:
                    continue
                out.append(Chunk(
                    chunk_id=f"land_{idx}",
                    source=os.path.basename(fpath),
                    chunk_type="land_freight",
                    text=f"[工厂到港拖车费] {text}",
                    metadata={"factory": str(row.get("发货工厂", "") or "").strip(),
                              "port": str(row.get("始发港", "") or "").strip()},
                ))
        except Exception as e:
            print(f"[RAG] 分块失败 {fpath}: {e}")
        return out

    def _chunk_time_analysis(self):
        out = []
        fpath = os.path.join(config.DATA_DIR, "工厂到起运港时效分析表.xlsx")
        if not os.path.exists(fpath):
            return out
        try:
            df = pd.read_excel(fpath, sheet_name=0)
            for idx, (_, row) in enumerate(df.iterrows()):
                text = _row_text(df, row)
                if not text:
                    continue
                out.append(Chunk(
                    chunk_id=f"transit_{idx}",
                    source=os.path.basename(fpath),
                    chunk_type="transit_time",
                    text=f"[工厂到港时效] {text}",
                    metadata={"factory": str(row.get("发货工厂", "") or "").strip(),
                              "port": str(row.get("始发港", "") or "").strip()},
                ))
        except Exception as e:
            print(f"[RAG] 分块失败 {fpath}: {e}")
        return out

    def _chunk_country_dest_ports(self):
        out = []
        fpath = config.COUNTRY_DEST_PORT_FILE
        if not os.path.exists(fpath):
            return out
        try:
            df = pd.read_excel(fpath, sheet_name=0)
            for idx, (_, row) in enumerate(df.iterrows()):
                text = _row_text(df, row)
                if not text:
                    continue
                out.append(Chunk(
                    chunk_id=f"mapping_{idx}",
                    source=os.path.basename(fpath),
                    chunk_type="mapping",
                    text=f"[运抵国与目的港] {text}",
                    metadata={"country": str(row.get("运抵国", "") or row.get("国家", "") or "").strip()},
                ))
        except Exception as e:
            print(f"[RAG] 分块失败 {fpath}: {e}")
        return out

    def _chunk_box_volume(self):
        out = []
        fpath = os.path.join(config.DATA_DIR, "集装箱标准容积对照表.xlsx")
        if not os.path.exists(fpath):
            return out
        try:
            df = pd.read_excel(fpath, sheet_name=0)
            for idx, (_, row) in enumerate(df.iterrows()):
                text = _row_text(df, row)
                if not text:
                    continue
                out.append(Chunk(
                    chunk_id=f"constant_{idx}",
                    source=os.path.basename(fpath),
                    chunk_type="constant",
                    text=f"[集装箱标准容积] {text}",
                    metadata={},
                ))
        except Exception as e:
            print(f"[RAG] 分块失败 {fpath}: {e}")
        return out

    def _chunk_kb_knowledge(self, kb):
        """把 KnowledgeBase 内存知识转成可检索的知识 chunk"""
        out = []
        # 工厂
        for name, info in kb.factory_info.items():
            text = (f"工厂: {name} | 简称: {info.get('short_name', '')} | 区域: {info.get('region', '')} "
                    f"| 省份: {info.get('province', '')} | 默认港: {info.get('default_port', '')} "
                    f"| 产品: {','.join(info.get('products', []))}")
            out.append(Chunk(chunk_id=f"kb_factory_{name}", source="KnowledgeBase", chunk_type="knowledge",
                             text=text, metadata={"factory": name}))
        # 国家 -> 目的港/条款/海运天数
        for country, ports in kb.country_dest_ports.items():
            port_names = ", ".join(p["port"] for p in ports) or "未知"
            terms = ", ".join(f"{t['term']}({t['count']}次)" for t in kb.country_trade_terms.get(country, [])) or "未知"
            days = kb.country_ocean_days.get(country)
            text = (f"运抵国: {country} | 常用目的港: {port_names} | 常用贸易条款: {terms} "
                    f"| 海运天数: {days.get('median', '?') if isinstance(days, dict) else days} 天")
            out.append(Chunk(chunk_id=f"kb_country_{country}", source="KnowledgeBase", chunk_type="knowledge",
                             text=text, metadata={"country": country}))
        # 贸易条款
        for term, info in kb.trade_terms.items():
            text = (f"贸易条款 {term} ({info.get('full', '')}): {info.get('desc', '')} "
                    f"| 卖方责任: {info.get('seller_resp', '')} | 费用范围: {info.get('cost_scope', '')}")
            out.append(Chunk(chunk_id=f"kb_term_{term}", source="KnowledgeBase", chunk_type="knowledge",
                             text=text, metadata={"term": term}))
        # 船公司
        for route, lines in kb.shipping_lines.items():
            for line in lines:
                text = (f"船公司: {line.get('name', '')} ({line.get('code', '')}) | 航线: {route} "
                        f"| 航程: {line.get('transit_days', '?')}天 | 班期: {line.get('frequency', '')} "
                        f"| 优势: {line.get('advantage', '')}")
                out.append(Chunk(chunk_id=f"kb_line_{route}_{line.get('code', '')}", source="KnowledgeBase",
                                 chunk_type="knowledge", text=text, metadata={"route": route}))
        # 箱型
        for box, vol in kb.box_types.items():
            out.append(Chunk(chunk_id=f"kb_box_{box}", source="KnowledgeBase", chunk_type="knowledge",
                             text=f"集装箱箱型 {box} 标准容积 {vol} CBM", metadata={"box_type": box}))
        # 海运天数统计
        for country, days in kb.country_ocean_days.items():
            median = days.get("median") if isinstance(days, dict) else days
            out.append(Chunk(chunk_id=f"kb_ocean_{country}", source="KnowledgeBase", chunk_type="knowledge",
                             text=f"运抵国 {country} 海运天数约 {median} 天", metadata={"country": country}))
        return out

    # ===== 索引 =====
    # ===== 报告文档（data/report 下的 docx / html）分块 =====
    def _chunk_report_docs(self):
        """把 data/report 下的分析报告（docx/html）按章节切分为可检索 chunk"""
        out = []
        report_dir = getattr(config, "REPORT_DIR", os.path.join(config.DATA_DIR, "report"))
        if not os.path.isdir(report_dir):
            return out
        for fname in sorted(os.listdir(report_dir)):
            fpath = os.path.join(report_dir, fname)
            if not os.path.isfile(fpath):
                continue
            ext = os.path.splitext(fname)[1].lower()
            try:
                if ext == ".docx":
                    out += self._chunk_docx_report(fpath)
                elif ext == ".html":
                    out += self._chunk_html_report(fpath)
            except Exception as e:
                print(f"[RAG] 报告分块失败 {fname}: {e}")
        return out

    def _chunk_docx_report(self, fpath):
        try:
            from docx import Document
            from docx.table import Table
            from docx.text.paragraph import Paragraph
            from docx.oxml.ns import qn
        except ImportError:
            print("[RAG] 未安装 python-docx，跳过 docx 报告索引")
            return []

        def iter_blocks(doc):
            body = doc.element.body
            for child in body.iterchildren():
                if child.tag == qn("w:p"):
                    yield Paragraph(child, doc)
                elif child.tag == qn("w:tbl"):
                    yield Table(child, doc)

        doc = Document(fpath)
        title = None
        sections = []          # (section_title, [lines])
        cur_title = None
        cur_lines = []
        pre_lines = []

        def flush():
            nonlocal cur_title, cur_lines
            if cur_title is not None and cur_lines:
                sections.append((cur_title, cur_lines))
            cur_title = None
            cur_lines = []

        for block in iter_blocks(doc):
            if isinstance(block, Table):
                for row in block.rows:
                    cells = [c.text.strip().replace("\n", " ") for c in row.cells]
                    cells = [c for c in cells if c]
                    if cells:
                        cur_lines.append(" | ".join(cells))
                continue
            text = block.text.strip()
            if not text:
                continue
            style = (block.style.name or "") if block.style is not None else ""
            if "Heading 1" in style or "标题 1" in style:
                title = text
                continue
            if "Heading" in style or "标题" in style:
                flush()
                cur_title = text
                continue
            if cur_title is None:
                pre_lines.append(text)
            else:
                cur_lines.append(text)
        flush()

        if title is None:
            title = os.path.splitext(os.path.basename(fpath))[0]
        prefix = f"[报告 {title}]"
        idx = 0
        out = []
        if pre_lines:
            out.append(Chunk(
                chunk_id=f"report_{idx}", source=os.path.basename(fpath),
                chunk_type="report",
                text=f"{prefix} {title}\n" + "\n".join(pre_lines),
                metadata={"report": title, "section": "概述"},
            ))
            idx += 1
        for sec_title, lines in sections:
            body = "\n".join(lines)
            if not body:
                continue
            for part in self._split_long_text(body, max_chars=1400):
                out.append(Chunk(
                    chunk_id=f"report_{idx}", source=os.path.basename(fpath),
                    chunk_type="report",
                    text=f"{prefix} {sec_title}\n{part}",
                    metadata={"report": title, "section": sec_title},
                ))
                idx += 1
        return out

    def _split_long_text(self, text, max_chars=1400):
        """超长章节按段落切块（保持段落完整）"""
        if len(text) <= max_chars:
            return [text]
        parts, buf, size = [], [], 0
        for para in text.split("\n"):
            buf.append(para)
            size += len(para) + 1
            if size >= max_chars:
                parts.append("\n".join(buf))
                buf, size = [], 0
        if buf:
            parts.append("\n".join(buf))
        return parts

    def _chunk_html_report(self, fpath):
        try:
            from bs4 import BeautifulSoup
            soup = BeautifulSoup(open(fpath, encoding="utf-8").read(), "html.parser")
            for tag in soup(["script", "style"]):
                tag.decompose()
            text = soup.get_text("\n")
        except ImportError:
            raw = open(fpath, encoding="utf-8").read()
            text = re.sub(r"<[^>]+>", " ", raw)
        lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
        title = lines[0] if lines else os.path.splitext(os.path.basename(fpath))[0]
        body = "\n".join(lines[1:] or [text])
        return [Chunk(
            chunk_id="report_html_0", source=os.path.basename(fpath),
            chunk_type="report",
            text=f"[报告 {title}]\n{body}",
            metadata={"report": title, "section": "全文"},
        )]

    def _build_keyword_index(self):
        self._chunk_tokens = [Counter(tokenize(c.text)) for c in self.chunks]
        df_counts = Counter()
        for ctr in self._chunk_tokens:
            for tok in set(ctr):
                df_counts[tok] += 1
        n = max(1, len(self.chunks))
        self._idf = {tok: np.log((n + 1) / (freq + 1)) + 1.0 for tok, freq in df_counts.items()}

    def _build_embeddings(self):
        texts = [c.text for c in self.chunks]
        if not texts:
            self._embeddings = np.zeros((0, 1), dtype=np.float32)
            return
        if self._embedding_enabled:
            try:
                vecs = _Embedder.encode(texts, config.EMBEDDING_MODEL)
                self._embeddings = np.asarray(vecs, dtype=np.float32)
                return
            except Exception as e:
                print(f"[RAG] 语义向量加载失败，回退哈希向量: {e}")
        self._embeddings = _hash_embed(texts, dim=config.EMBEDDING_HASH_DIM)

    def _record_file_mtimes(self):
        self._file_mtimes = {}
        for f in [config.FACTORY_ALLOCATION_FILE, config.CONTRACT_FREIGHT_FILE,
                  config.PORT_MISC_STANDARD_FILE, config.ROUTE_PRICING_FILE,
                  os.path.join(config.DATA_DIR, "工厂到起运港时效分析表.xlsx"),
                  config.COUNTRY_DEST_PORT_FILE,
                  os.path.join(config.DATA_DIR, "集装箱标准容积对照表.xlsx")]:
            try:
                if os.path.exists(f):
                    self._file_mtimes[f] = os.path.getmtime(f)
            except Exception:
                pass
        report_dir = getattr(config, "REPORT_DIR", os.path.join(config.DATA_DIR, "report"))
        if os.path.isdir(report_dir):
            for fname in sorted(os.listdir(report_dir)):
                fp = os.path.join(report_dir, fname)
                if os.path.isfile(fp):
                    try:
                        self._file_mtimes[fp] = os.path.getmtime(fp)
                    except Exception:
                        pass

    def refresh_if_changed(self):
        """检测 Excel 文件变更，有变化则重建索引"""
        changed = False
        for f, old_mtime in self._file_mtimes.items():
            try:
                if os.path.exists(f) and os.path.getmtime(f) != old_mtime:
                    changed = True
                    break
            except Exception:
                continue
        if changed:
            print("[RAG] 检测到数据文件变更，重建索引")
            self._built = False
            self.build(force=True)

    # ===== 检索 =====
    def search(self, query, top_k=8, chunk_types=None, exact_terms=None):
        """混合检索：关键词(BM25风格) + 向量(语义/哈希) 加权融合

        :param query: 查询文本
        :param top_k: 返回条数
        :param chunk_types: 过滤 chunk_type 列表，如 ['rule', 'quote']
        :param exact_terms: 需要精确命中的词（提升命中 chunk 的分数）
        :return: [Chunk]
        """
        if not self.chunks:
            return []
        if not self._built:
            self.build()

        n = len(self.chunks)
        if chunk_types:
            mask = np.array([c.chunk_type in chunk_types for c in self.chunks], dtype=bool)
        else:
            mask = np.ones(n, dtype=bool)

        # 关键词分数
        kw = np.zeros(n, dtype=np.float32)
        qt = Counter(tokenize(query))
        for tok, qf in qt.items():
            idf = self._idf.get(tok, 0.0)
            if idf <= 0:
                continue
            for i in range(n):
                if not mask[i]:
                    continue
                tf = self._chunk_tokens[i].get(tok, 0)
                if tf > 0:
                    kw[i] += qf * idf * (1.0 + np.log(tf))

        # 向量分数（余弦）
        vec = np.zeros(n, dtype=np.float32)
        qv = _hash_embed([query], dim=config.EMBEDDING_HASH_DIM)[0] if not self._embedding_enabled else None
        if qv is not None:
            dots = self._embeddings @ qv
            vec = np.where(mask, dots, 0.0).astype(np.float32)
        else:
            try:
                qvec = _Embedder.encode([query], config.EMBEDDING_MODEL)[0]
                dots = self._embeddings @ qvec
                vec = np.where(mask, dots, 0.0).astype(np.float32)
            except Exception:
                vec = np.where(mask, 0.0, 0.0).astype(np.float32)

        # 归一化融合
        kw_norm = (kw - kw.min()) / (kw.max() - kw.min() + 1e-9) if kw.max() > 0 else kw
        vec_norm = (vec - vec.min()) / (vec.max() - vec.min() + 1e-9) if vec.max() > 0 else vec
        fused = 0.6 * kw_norm + 0.4 * vec_norm

        # 精确词提升
        if exact_terms:
            for term in exact_terms:
                if not term:
                    continue
                term = str(term).strip().lower()
                if len(term) < 2:
                    continue
                for i, c in enumerate(self.chunks):
                    if mask[i] and term in c.text.lower():
                        fused[i] += 0.35

        idxs = np.argsort(-fused)[:top_k]
        results = []
        for i in idxs:
            if fused[i] <= 0:
                continue
            c = self.chunks[i]
            c.score = round(float(fused[i]), 4)
            results.append(c)
        return results


    def stats(self):
        """返回检索库统计信息（供 /api/kb/stats 与页面展示）"""
        if not self._built:
            self.build()
        types = {}
        sources = set()
        for c in self.chunks:
            types[c.chunk_type] = types.get(c.chunk_type, 0) + 1
            sources.add(c.source)
        return {
            "chunks": len(self.chunks),
            "chunk_types": types,
            "embedding": "semantic" if self._embedding_enabled else "hash-fallback",
            "embedding_model": config.EMBEDDING_MODEL if self._embedding_enabled else None,
            "sources": sorted(sources),
            "built_at": self._built_at,
        }


def get_rag_store():
    """获取全局 RagStore 单例（惰性构建）"""
    store = RagStore()
    if not store._built:
        store.build()
    return store